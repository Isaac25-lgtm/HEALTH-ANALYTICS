"""Keep a single-process (eager) deployment current without a worker or scheduler service.

In queue mode Celery Beat schedules the bounded DHIS2 refresh. A workstation or small single-server
deployment has neither Redis nor a worker, so nothing renewed the short-lived MPDSR event cache and
the MPDSR pages went blank a day after every manual refresh. Here the API itself starts the same
supervised refresh script, in a separate process, whenever the last successful Tracker
synchronisation is older than the configured interval. It never writes to DHIS2 and adds no new
extraction path: it only decides *when* to run ``scripts/dhis2_refresh.py``.
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.domain.enums import ConnectorType, JobStatus
from app.models import SyncJob
from app.services.purge import acquire_lease
from app.services.sync import reclaim_abandoned_sync_jobs

CHECK_EVERY_SECONDS = 15 * 60
FIRST_CHECK_AFTER_SECONDS = 20
# A refresh that has been "running" longer than this is treated as abandoned, not as in progress.
IN_PROGRESS_WINDOW = timedelta(hours=3)
# After any attempt, successful or not, wait before trying again: a slow or unavailable source
# server must not be asked again every few minutes.
RETRY_AFTER = timedelta(hours=2)
REFRESH_LEASE = "local_scheduler:dhis2_refresh"
PURGE_LEASE = "local_scheduler:retention_purge"
PURGE_EVERY = timedelta(hours=20)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def refresh_is_due(session: Session, settings: Settings, now: datetime | None = None) -> bool:
    """True when extraction is enabled, none is in progress and the last Tracker success is too old."""
    if not (settings.dhis2_enabled and settings.sync_enabled and settings.dhis2_refresh_schedule_enabled):
        return False
    moment = now or datetime.now(UTC)
    refresh_types = [ConnectorType.TRACKER.value, ConnectorType.AGGREGATE.value]
    recent = session.scalars(
        select(SyncJob.created_at).where(
            SyncJob.job_type.in_(refresh_types),
            SyncJob.status.in_([JobStatus.QUEUED.value, JobStatus.RUNNING.value]),
            SyncJob.idempotency_key.like("scheduled:%"),
        )
    ).all()
    if any(moment - _aware(created) < IN_PROGRESS_WINDOW for created in recent if created is not None):
        return False
    last_attempt = _aware(
        session.scalar(
            select(func.max(SyncJob.created_at)).where(
                SyncJob.job_type.in_(refresh_types), SyncJob.idempotency_key.like("scheduled:%")
            )
        )
    )
    if last_attempt is not None and moment - last_attempt < RETRY_AFTER:
        return False
    last_success = _aware(
        session.scalar(
            select(func.max(SyncJob.finished_at)).where(
                SyncJob.job_type == ConnectorType.TRACKER.value,
                SyncJob.status == JobStatus.SUCCEEDED.value,
            )
        )
    )
    interval = timedelta(hours=settings.dhis2_refresh_interval_hours)
    return last_success is None or moment - last_success >= interval


class LocalRefreshScheduler:
    """A daemon thread that starts the refresh script when it is due. One refresh at a time."""

    def __init__(self) -> None:
        self._process: subprocess.Popen | None = None
        self._purge: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._holder = uuid4().hex

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="local-refresh-scheduler", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        time.sleep(FIRST_CHECK_AFTER_SECONDS)
        while True:
            try:
                self.check_once()
            except Exception:  # noqa: BLE001 - the scheduler must never take the API down
                pass
            time.sleep(CHECK_EVERY_SECONDS)

    def check_once(self) -> bool:
        if self._process is not None and self._process.poll() is None:
            return False
        from app.db.session import get_session_factory

        settings = get_settings()
        with get_session_factory()() as session:
            try:
                reclaim_abandoned_sync_jobs(session)
            except Exception:  # noqa: BLE001 - tidying up must not stop the refresh decision
                session.rollback()
            self._purge_if_enabled(session, settings)
            due = refresh_is_due(session, settings)
            # Two API processes can reach the same decision in the same second. The lease is taken
            # in the database, so exactly one of them starts the refresh; it lapses by itself.
            if due and not acquire_lease(
                session, REFRESH_LEASE, self._holder, int(RETRY_AFTER.total_seconds())
            ):
                due = False
        if not due:
            return False
        backend_root = Path(__file__).resolve().parents[2]
        self._process = subprocess.Popen(  # noqa: S603 - fixed arguments, this interpreter
            [sys.executable, str(backend_root / "scripts" / "dhis2_refresh.py"), "--scheduled"],
            cwd=str(backend_root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return True


    def _purge_if_enabled(self, session: Session, settings: Settings) -> None:
        """Run the governed retention purge about once a day, only when the operator opted in.

        Expired MPDSR events are already excluded from every calculation, but excluded is not
        deleted. In queue mode Celery Beat schedules the purge; here nothing did. This starts the
        same ``scripts/purge_expired.py`` and adds no deletion rule of its own.
        """
        if not (settings.purge_enabled and settings.purge_schedule_enabled):
            return
        if self._purge is not None and self._purge.poll() is None:
            return
        if not acquire_lease(session, PURGE_LEASE, self._holder, int(PURGE_EVERY.total_seconds())):
            return
        backend_root = Path(__file__).resolve().parents[2]
        self._purge = subprocess.Popen(  # noqa: S603 - fixed arguments, this interpreter
            [sys.executable, str(backend_root / "scripts" / "purge_expired.py"), "--source", "scheduler"],
            cwd=str(backend_root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )


scheduler = LocalRefreshScheduler()

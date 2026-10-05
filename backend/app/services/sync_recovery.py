"""Recover committed-but-unpublished sync jobs using the existing durable job table.

Delivery is at least once. The worker's conditional claim and PostgreSQL execution lock
remain authoritative. Never reclaim extraction failures or already-running jobs here.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased

from app.config import get_settings
from app.models import SyncJob
from app.services.sync import SyncDispatchError, dispatch_sync_job, should_run_eager

DISPATCH_FAILURE_CODES = ("sync_enqueue_failed", "facility_load_failed")


def recover_sync_dispatch(session, *, now=None, limit=100, min_age_seconds=60, dispatch=None) -> dict:
    settings = get_settings()
    result = {"published": 0, "publication_failed": 0, "skipped": 0, "disabled": False}
    if not settings.dhis2_enabled or not settings.sync_enabled or should_run_eager():
        return {**result, "disabled": True}
    # Import after the connector stack has initialised. Importing observability
    # first re-enters dhis2.__init__ through redaction during a fresh CLI process.
    from app.services.observability import record_operational_event
    if not 1 <= limit <= 1000 or min_age_seconds < 1:
        raise ValueError("Recovery requires a bounded batch and a positive retry delay.")
    dispatch = dispatch or dispatch_sync_job
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(seconds=min_age_seconds)
    eligible = and_(
        SyncJob.cancelled.is_(False),
        SyncJob.started_at.is_(None),
        SyncJob.updated_at <= cutoff,
        or_(
            SyncJob.status == "queued",
            and_(SyncJob.status == "failed", SyncJob.error_code.in_(DISPATCH_FAILURE_CODES)),
        ),
    )
    # A new facility request may already have replaced a failed publication attempt.
    # Do not re-activate the old key alongside it, or let it block the entire sweep.
    other = aliased(SyncJob)
    duplicate = (
        select(other.id)
        .where(
            other.id != SyncJob.id,
            other.job_type == "aggregate_facilities",
            other.idempotency_key == SyncJob.idempotency_key,
            other.status.in_(("queued", "running")),
        )
        .exists()
    )
    no_duplicate = ~and_(SyncJob.job_type == "aggregate_facilities", SyncJob.idempotency_key.is_not(None), duplicate)
    ids = session.scalars(
        select(SyncJob.id).where(eligible, no_duplicate).order_by(SyncJob.updated_at, SyncJob.id).limit(limit)
    ).all()
    for job_id in ids:
        try:
            with session.begin_nested():
                claimed = session.execute(
                    update(SyncJob)
                    .where(SyncJob.id == job_id, eligible, no_duplicate)
                    .values(status="queued", updated_at=now, finished_at=None, error_code=None, error_message=None)
                ).rowcount
            # Persist the retry clock before contacting the broker. A crash on either side
            # is retried after the delay; duplicate publication is safe at the worker.
            session.commit()
        except IntegrityError:
            session.rollback()
            result["skipped"] += 1
            continue
        if not claimed:
            result["skipped"] += 1
            continue
        try:
            dispatch(job_id)
            record_operational_event("sync_dispatch_recovered", job_id=str(job_id), session=session)
            result["published"] += 1
        except SyncDispatchError:
            session.execute(
                update(SyncJob)
                .where(SyncJob.id == job_id, SyncJob.status == "queued")
                .values(
                    updated_at=now,
                    error_code="sync_enqueue_failed",
                    error_message="Worker publication failed; durable dispatch recovery will retry.",
                )
            )
            record_operational_event("sync_dispatch_recovery_failed", job_id=str(job_id), session=session)
            result["publication_failed"] += 1
        session.commit()
    return result

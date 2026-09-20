"""Scheduled DHIS2 aggregate refresh.

The owner's refresh decision is a six-hourly pass over recent, still-open periods, never
continuous polling and never a repeated sweep of closed historical periods. This command is the
scheduled entry point for that, and it is wired into render.yaml.

It cannot contact DHIS2 until DHIS2_ENABLED and SYNC_ENABLED are both true, configuration is
complete, and approved source/org-unit mappings exist. Disabled deployments stay inert. Enabled
deployments enqueue one bounded aggregate job per programme, mapping version and recent/open
period; they never sweep closed historical periods.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import get_settings, validate_runtime_settings  # noqa: E402
from app.db.session import get_session_factory  # noqa: E402
from app.domain.enums import ConnectorType, JobStatus  # noqa: E402
from app.domain.periods import uganda_fy_key  # noqa: E402
from app.models import OrgUnit, OrgUnitMapping, Programme, SourceMapping, SyncJob  # noqa: E402
from app.services.sync import (  # noqa: E402
    SyncDispatchError,
    dispatch_sync_job,
    enqueue_sync_job,
    execute_sync_job,
    should_run_eager,
)

# Refresh only periods that can still change.
RECENT_MONTHS = 3


def _recent_periods(today: date) -> list[str]:
    periods: list[str] = []
    year, month = today.year, today.month
    for _ in range(RECENT_MONTHS):
        periods.append(f"{year}{month:02d}")
        month -= 1
        if month == 0:
            month, year = 12, year - 1
    periods.append(uganda_fy_key(today))
    return periods


def _bucket(now: datetime) -> str:
    return now.strftime("%Y%m%d") + f"{(now.hour // 6) * 6:02d}"


def _mapping_sets(session) -> list[tuple[Programme, str]]:
    rows = session.execute(
        select(Programme, SourceMapping.mapping_version)
        .join(SourceMapping, SourceMapping.programme_id == Programme.id)
        .where(SourceMapping.enabled.is_(True), SourceMapping.dhis2_item_uid.is_not(None))
        .distinct()
        .order_by(Programme.code, SourceMapping.mapping_version)
    ).all()
    return [(programme, str(version)) for programme, version in rows]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scheduled", action="store_true", help="Run as the scheduled six-hourly job.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    settings = get_settings()
    today = datetime.now(UTC).date()
    plan = {
        "mode": "inert",
        "scheduled": bool(args.scheduled),
        "cadence": "every six hours for recent, still-open periods",
        "periods_that_would_refresh": _recent_periods(today),
        "closed_periods_refreshed": False,
        "continuous_polling": False,
        "dhis2_enabled": settings.dhis2_enabled,
        "sync_enabled": settings.sync_enabled,
        "blocked_reasons": [],
    }
    if not settings.dhis2_enabled:
        plan["blocked_reasons"].append("DHIS2_ENABLED is false.")
    if not settings.sync_enabled:
        plan["blocked_reasons"].append("SYNC_ENABLED is false.")
    plan["blocked_reasons"].extend(error for error in validate_runtime_settings(settings) if "DHIS2" in error)

    if plan["blocked_reasons"]:
        print(json.dumps(plan, indent=2) if args.json else
              "DHIS2 refresh is not enabled; nothing was contacted. " + "; ".join(plan["blocked_reasons"]))
        return 0

    session = get_session_factory()()
    try:
        root = session.scalar(
            select(OrgUnit).where(
                OrgUnit.code == "UG",
                OrgUnit.parent_id.is_(None),
                OrgUnit.active.is_(True),
            )
        )
        mapping_sets = _mapping_sets(session)
        org_mapping_exists = session.scalar(
            select(OrgUnitMapping.id).where(OrgUnitMapping.source_system == "dhis2").limit(1)
        )
        if root is None or not mapping_sets or org_mapping_exists is None:
            if root is None:
                reason = "The approved Uganda root is missing."
            elif not mapping_sets:
                reason = "No enabled DHIS2 source mappings exist."
            else:
                reason = "No approved DHIS2 organisation-unit mappings exist."
            plan["mode"] = "blocked"
            plan["blocked_reasons"] = [reason]
            print(json.dumps(plan, indent=2) if args.json else plan["blocked_reasons"][0])
            return 3

        now = datetime.now(UTC)
        jobs: list[SyncJob] = []
        new_jobs: list[SyncJob] = []
        reused = 0
        for programme, mapping_version in mapping_sets:
            for period in plan["periods_that_would_refresh"]:
                key = f"scheduled:{_bucket(now)}:{programme.code}:{mapping_version}:{period}"
                existing = session.scalar(select(SyncJob).where(SyncJob.idempotency_key == key))
                if existing is not None:
                    jobs.append(existing)
                    reused += 1
                    continue
                created = enqueue_sync_job(
                    session,
                    org_unit=root,
                    periods=[period],
                    user=None,
                    job_type=ConnectorType.AGGREGATE.value,
                    programme_id=programme.id,
                    mapping_version=mapping_version,
                    idempotency_key=key,
                )
                jobs.append(created)
                new_jobs.append(created)
        session.commit()

        dispatched = 0
        failed = 0
        for job in new_jobs:
            if job.status != JobStatus.QUEUED.value or job.idempotency_key is None:
                continue
            if should_run_eager():
                execute_sync_job(session, job.id)
                session.commit()
            else:
                try:
                    dispatch_sync_job(job.id)
                    dispatched += 1
                except SyncDispatchError:
                    job.status = JobStatus.FAILED.value
                    job.error_code = "sync_enqueue_failed"
                    job.error_message = "The scheduled sync job could not be submitted to the worker queue."
                    job.finished_at = datetime.now(UTC)
                    session.commit()
                    failed += 1

        plan.update(
            {
                "mode": "executed" if failed == 0 else "failed",
                "mapping_sets": [
                    {"programme": programme.code, "mapping_version": version}
                    for programme, version in mapping_sets
                ],
                "job_count": len(jobs),
                "reused_count": reused,
                "dispatched_count": dispatched,
                "failed_count": failed,
                "jobs": [{"id": str(job.id), "status": job.status} for job in jobs],
            }
        )
        print(json.dumps(plan, indent=2) if args.json else f"Scheduled {len(jobs)} bounded DHIS2 refresh jobs.")
        return 4 if failed else 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())

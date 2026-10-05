"""Rebind an internal source key to a DHIS2 indicator and extract it natively (D-065).

A DHIS2 indicator is a ratio computed by DHIS2. It cannot be summed from districts or from months,
so this command extracts it for the national and regional units as well as every district/city,
and for each month, financial year, financial-year quarter and calendar year natively.

Steps, each audited:
  1. Rebind the mapping (same key, version and programme) to the indicator UID.
  2. Retire every current raw row for the key that came from the previous binding or from a month
     roll-up; rows are kept (``is_current = false``) for audit, never deleted.
  3. Extract period by period, one sync job each; the run is resumable.

    python scripts/apply_direct_indicator.py --key KMC_PERCENT --programme MNCH \
        --indicator-uid DUFsfDA9YD2 --approved-by biostat.pader --reference D-065 --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select, update  # noqa: E402

from app.db.session import get_session_factory  # noqa: E402
from app.domain.enums import ActionPermission, ConnectorType, JobStatus  # noqa: E402
from app.integrations.dhis2.aggregate import AggregateAnalyticsAdapter  # noqa: E402
from app.integrations.dhis2.errors import Dhis2Error  # noqa: E402
from app.integrations.dhis2.http import Dhis2HttpClient  # noqa: E402
from app.models import AuditLog, OrgUnit, Programme, RawAggregateValue, SourceMapping, SyncJob, User  # noqa: E402
from app.services.authorization import require_action, require_org_unit_access, require_programme_access  # noqa: E402
from app.services.sync import (  # noqa: E402
    _aggregate_level_uids,
    _fetch_aggregate_periods,
    _finish,
    _mapped_org_unit_uids,
    enqueue_sync_job,
    persist_aggregate_observations,
)

MAPPING_VERSION = "live-2026-09-21"


def periods_to_extract(first_fy: int, today: date) -> list[str]:
    """Closed months from July of ``first_fy`` plus every FY, FY quarter and calendar year touched."""
    months: list[str] = []
    year, month = first_fy, 7
    last = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
    while (year, month) <= last:
        months.append(f"{year}{month:02d}")
        month += 1
        if month > 12:
            month, year = 1, year + 1
    fys = sorted({int(key[:4]) if int(key[4:]) >= 7 else int(key[:4]) - 1 for key in months})
    periods = list(months)
    for start in fys:
        fy = f"FY{start}/{str(start + 1)[2:]}"
        periods.append(fy)
        periods.extend(f"{fy}Q{quarter}" for quarter in range(1, 5))
    periods.extend(sorted({key[:4] for key in months}))
    return periods


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--key", required=True)
    parser.add_argument("--programme", required=True)
    parser.add_argument("--indicator-uid", required=True)
    parser.add_argument("--approved-by", required=True)
    parser.add_argument("--reference", required=True, help="Owner decision reference, e.g. D-065.")
    parser.add_argument("--first-fy", type=int, default=2020)
    parser.add_argument("--pause-seconds", type=float, default=1.5)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    session = get_session_factory()()
    try:
        approver = session.scalar(select(User).where(User.username == args.approved_by, User.is_active.is_(True)))
        if approver is None:
            raise SystemExit(f"Approver {args.approved_by!r} is not an active user.")
        require_action(session, approver, ActionPermission.MANAGE_MAPPINGS)
        require_action(session, approver, ActionPermission.MANAGE_SYNC)
        require_programme_access(session, approver, args.programme)
        if not args.reference.strip():
            raise SystemExit("An approval reference is required.")
        programme = session.scalar(select(Programme).where(Programme.code == args.programme))
        uganda = session.scalar(select(OrgUnit).where(OrgUnit.code == "UG", OrgUnit.parent_id.is_(None)))
        if programme is None or uganda is None:
            raise SystemExit("The approved programme and Uganda hierarchy must exist.")
        require_org_unit_access(session, approver, uganda.id)
        mapping = session.scalar(
            select(SourceMapping).where(
                SourceMapping.internal_source_key == args.key,
                SourceMapping.programme_id == programme.id,
                SourceMapping.mapping_version == MAPPING_VERSION,
            )
        )
        if mapping is None:
            raise SystemExit(f"No {MAPPING_VERSION} mapping exists for {args.key}.")
        periods = periods_to_extract(args.first_fy, datetime.now(UTC).date())
        done = {
            row.period_from
            for row in session.scalars(
                select(SyncJob).where(
                    SyncJob.programme_id == programme.id,
                    SyncJob.status == JobStatus.SUCCEEDED.value,
                    SyncJob.notes.like(f"{args.reference} {args.key}%"),
                )
            ).all()
        }
        pending = [period for period in periods if period not in done]
        plan = {
            "key": args.key,
            "previous_binding": {"uid": mapping.dhis2_item_uid, "item_kind": mapping.item_kind},
            "new_binding": {"uid": args.indicator_uid, "item_kind": "indicator"},
            "periods": len(periods),
            "pending_jobs": len(pending),
        }
        if args.dry_run:
            print(json.dumps({"mode": "dry_run", **plan}, indent=2))
            return 0

        if mapping.dhis2_item_uid != args.indicator_uid or mapping.item_kind != "indicator":
            before = {
                "uid": mapping.dhis2_item_uid,
                "item_kind": mapping.item_kind,
                "semantics": mapping.aggregation_semantics,
            }
            mapping.dhis2_item_uid = args.indicator_uid
            mapping.item_kind = "indicator"
            mapping.aggregation_semantics = "SUM"  # DHIS2 computes the indicator natively per period
            mapping.notes = f"{args.reference}: DHIS2 indicator; previously {before['uid']} ({before['item_kind']})."
            retired = session.execute(
                update(RawAggregateValue)
                .where(
                    RawAggregateValue.internal_source_key == args.key,
                    RawAggregateValue.programme_id == programme.id,
                    RawAggregateValue.is_current.is_(True),
                )
                .values(is_current=False)
            ).rowcount
            session.add(
                AuditLog(
                    actor_user_id=approver.id,
                    action="source_mapping_rebound",
                    resource_type="source_mapping",
                    resource_id=str(mapping.id),
                    before_json=before,
                    after_json={
                        "uid": args.indicator_uid,
                        "item_kind": "indicator",
                        "reference": args.reference,
                        "raw_rows_retired": retired,
                    },
                )
            )
            session.commit()
            print(json.dumps({"rebound": True, "raw_rows_retired": retired}))

        ou_uids = _mapped_org_unit_uids(session, uganda) + _aggregate_level_uids(session, uganda)
        succeeded = failed = 0
        with Dhis2HttpClient() as http:
            adapter = AggregateAnalyticsAdapter(http)
            for index, period in enumerate(pending, 1):
                job = enqueue_sync_job(
                    session,
                    org_unit=uganda,
                    periods=[period],
                    user=approver,
                    job_type=ConnectorType.AGGREGATE.value,
                    programme_id=programme.id,
                    mapping_version=MAPPING_VERSION,
                )
                job.notes = f"{args.reference} {args.key} native indicator extraction"
                job.status = JobStatus.RUNNING.value
                job.started_at = datetime.now(UTC)
                job.requested_count = 1
                try:
                    observations, received = _fetch_aggregate_periods(adapter, [mapping], ou_uids, [period])
                    by_uid = {(mapping.dhis2_item_uid, ""): mapping}
                    persist_aggregate_observations(session, job, observations, by_uid, datetime.now(UTC))
                    job.received_count = received
                    job.status = JobStatus.SUCCEEDED.value
                    succeeded += 1
                except Dhis2Error as exc:
                    job.status = JobStatus.FAILED.value
                    job.error_code = exc.code
                    failed += 1
                _finish(job)
                session.commit()
                print(f"[{index}/{len(pending)}] {period} -> {job.status} stored={job.stored_count}", flush=True)
                time.sleep(args.pause_seconds)
        print(json.dumps({"mode": "completed", **plan, "succeeded": succeeded, "failed": failed}, indent=2))
        return 0 if failed == 0 else 4
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())

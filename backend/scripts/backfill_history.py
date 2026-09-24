"""Backfill monthly DHIS2 history for every mapped programme, month by month.

Months are the single stored source of truth: financial years, quarters, calendar years and
custom ranges are all built from them afterwards (see ``app/services/period_rollup.py``), so
nothing needs to be extracted twice and every derived figure traces back to its months.

Owner decision 2026-09-24 (D-057): aggregate history from 2020 is retained long-term. It holds
district-month counts only, never identifiable records.

The command is idempotent and resumable. A programme-month that already has a succeeded job for
the mapping version is skipped, so an interrupted run simply continues where it stopped. Jobs run
one at a time with a pause between them, because the national instance is shared and degrades
under load.

    python scripts/backfill_history.py --start 202007 --end 202608 --dry-run
    python scripts/backfill_history.py --start 202007 --end 202608 --approved-by biostat.pader
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

from sqlalchemy import select  # noqa: E402

from app.db.session import get_session_factory  # noqa: E402
from app.domain.enums import ConnectorType, JobStatus  # noqa: E402
from app.models import AuditLog, OrgUnit, Programme, SourceMapping, SyncJob, User  # noqa: E402
from app.services.sync import enqueue_sync_job, execute_sync_job  # noqa: E402

MAPPING_VERSION = "live-2026-09-21"
PROGRAMMES = ("MNCH", "EPI", "MPDSR")
# MPDSR's reported-death counts read the same approved HMIS 105 elements MNCH already uses.
# Calculations select source rows by the indicator's own programme, so these must also be bound
# under MPDSR; otherwise the MPDSR screen reads nothing although the data exists.
MPDSR_SHARED_KEYS = ("MATERNAL_DEATHS", "NEWBORN_DEATHS", "FRESH_SB", "MACERATED_SB")


def month_range(start: str, end: str) -> list[str]:
    year, month = int(start[:4]), int(start[4:])
    last_year, last_month = int(end[:4]), int(end[4:])
    months: list[str] = []
    while (year, month) <= (last_year, last_month):
        months.append(f"{year}{month:02d}")
        month += 1
        if month > 12:
            month, year = 1, year + 1
    return months


def last_closed_month(today: date) -> str:
    year, month = today.year, today.month - 1
    if month == 0:
        year, month = year - 1, 12
    return f"{year}{month:02d}"


def ensure_mpdsr_wiring(session, approver: User, version: str) -> int:
    programmes = {p.code: p for p in session.scalars(select(Programme)).all()}
    mnch, mpdsr = programmes["MNCH"], programmes["MPDSR"]
    created = 0
    for key in MPDSR_SHARED_KEYS:
        source = session.scalar(
            select(SourceMapping).where(
                SourceMapping.internal_source_key == key,
                SourceMapping.mapping_version == version,
                SourceMapping.programme_id == mnch.id,
            )
        )
        if source is None:
            raise SystemExit(f"Approved MNCH mapping for {key} is missing; nothing was changed.")
        exists = session.scalar(
            select(SourceMapping).where(
                SourceMapping.internal_source_key == key,
                SourceMapping.mapping_version == version,
                SourceMapping.programme_id == mpdsr.id,
            )
        )
        if exists is not None:
            continue
        session.add(
            SourceMapping(
                internal_source_key=key,
                programme_id=mpdsr.id,
                dhis2_item_uid=source.dhis2_item_uid,
                category_option_combo_uid=source.category_option_combo_uid,
                item_kind=source.item_kind,
                aggregation_semantics=source.aggregation_semantics,
                mapping_version=version,
                enabled=True,
            )
        )
        created += 1
    if created:
        session.add(
            AuditLog(
                actor_user_id=approver.id,
                action="source_mappings_applied",
                resource_type="source_mapping",
                resource_id=version,
                after_json={
                    "approval_reference": "owner decision 2026-09-24: MPDSR reported-death counts",
                    "programme": "MPDSR",
                    "keys": list(MPDSR_SHARED_KEYS),
                    "copied_from_programme": "MNCH",
                    "mappings_created": created,
                },
            )
        )
    session.commit()
    return created


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", default="202007")
    parser.add_argument("--end", default=None, help="Defaults to the last closed month.")
    parser.add_argument("--programme", action="append", choices=PROGRAMMES)
    parser.add_argument("--approved-by")
    parser.add_argument("--pause-seconds", type=float, default=2.0)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    end = args.end or last_closed_month(datetime.now(UTC).date())
    months = month_range(args.start, end)
    programmes = args.programme or list(PROGRAMMES)

    session = get_session_factory()()
    try:
        uganda = session.scalar(select(OrgUnit).where(OrgUnit.code == "UG", OrgUnit.parent_id.is_(None)))
        by_code = {p.code: p for p in session.scalars(select(Programme)).all()}
        plan = []
        for code in programmes:
            done = {
                row.period_from
                for row in session.scalars(
                    select(SyncJob).where(
                        SyncJob.programme_id == by_code[code].id,
                        SyncJob.mapping_version == MAPPING_VERSION,
                        SyncJob.status == JobStatus.SUCCEEDED.value,
                    )
                ).all()
            }
            plan.extend((code, month) for month in months if month not in done)
        summary = {"months": f"{months[0]}..{months[-1]}", "programmes": programmes, "pending_jobs": len(plan)}
        if args.dry_run:
            print(json.dumps({"mode": "dry_run", **summary}, indent=2))
            return 0
        if not args.approved_by:
            parser.error("--approved-by is required to run the backfill")
        approver = session.scalar(select(User).where(User.username == args.approved_by))
        if approver is None or not approver.is_active:
            raise SystemExit(f"Approver {args.approved_by!r} is not an active user.")
        if "MPDSR" in programmes:
            print(json.dumps({"mpdsr_mappings_created": ensure_mpdsr_wiring(session, approver, MAPPING_VERSION)}))

        succeeded = failed = 0
        started = time.monotonic()
        for index, (code, month) in enumerate(plan, 1):
            outcome = None
            for attempt in range(1, args.attempts + 1):
                job = enqueue_sync_job(
                    session,
                    org_unit=uganda,
                    periods=[month],
                    user=approver,
                    job_type=ConnectorType.AGGREGATE.value,
                    programme_id=by_code[code].id,
                    mapping_version=MAPPING_VERSION,
                )
                session.commit()
                job = execute_sync_job(session, job.id)
                session.commit()
                outcome = job
                if job.status == JobStatus.SUCCEEDED.value:
                    break
                time.sleep(args.pause_seconds * 5 * attempt)
            if outcome is not None and outcome.status == JobStatus.SUCCEEDED.value:
                succeeded += 1
            else:
                failed += 1
            elapsed = int(time.monotonic() - started)
            print(
                f"[{index}/{len(plan)}] {code} {month} -> {outcome.status if outcome else 'none'} "
                f"stored={outcome.stored_count if outcome else 0} "
                f"err={(outcome.error_code if outcome else '') or ''} elapsed={elapsed}s",
                flush=True,
            )
            time.sleep(args.pause_seconds)
        print(json.dumps({"mode": "completed", **summary, "succeeded": succeeded, "failed": failed}, indent=2))
        return 0 if failed == 0 else 4
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())

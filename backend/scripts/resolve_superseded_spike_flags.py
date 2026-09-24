"""Resolve spike/drop flags raised by the pre-D-064 comparison against non-comparable periods.

Before D-064 the spike/drop rule compared a period's value with every other stored period, so a
financial-year total was compared with single months and flagged thousands of false threefold
changes. The corrected rule compares only with the immediately preceding period of the same kind.

This resolves, with an audit record each, only the open or acknowledged ANOMALOUS_SPIKE_DROP flags
whose reference period is not that comparable period. Flags the corrected rule would raise are
left untouched. Dry-run is the default.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime

from sqlalchemy import select

from app.db.session import get_session_factory
from app.domain.enums import QualityStatus
from app.domain.periods import PeriodError, previous_period
from app.models import DataQualityFlag, User
from app.services.audit import write_audit

RULE = "ANOMALOUS_SPIKE_DROP"
NOTE = (
    "Superseded by D-064: raised by the earlier spike/drop comparison against a non-comparable "
    "period. The corrected rule compares only with the immediately preceding period of the same kind."
)


def _comparable(period: str | None) -> str | None:
    if not period:
        return None
    try:
        return previous_period(period)
    except PeriodError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--user", help="Username recorded as the resolving user (required with --apply).")
    args = parser.parse_args()
    with get_session_factory()() as session:
        flags = session.scalars(
            select(DataQualityFlag).where(
                DataQualityFlag.rule_id == RULE,
                DataQualityFlag.status.in_([QualityStatus.OPEN.value, QualityStatus.ACKNOWLEDGED.value]),
            )
        ).all()
        superseded = [
            flag for flag in flags if (flag.evidence or {}).get("reference_period") != _comparable(flag.period)
        ]
        summary = {
            "mode": "apply" if args.apply else "dry_run",
            "open_spike_flags": len(flags),
            "superseded": len(superseded),
            "kept": len(flags) - len(superseded),
        }
        if args.apply:
            user = session.scalar(select(User).where(User.username == args.user, User.is_active.is_(True)))
            if user is None:
                print(json.dumps({"status": "failed", "message": "--apply requires an active --user."}))
                return 1
            now = datetime.now(UTC)
            for flag in superseded:
                before = {"status": flag.status, "resolution_note": flag.resolution_note}
                flag.status = QualityStatus.RESOLVED.value
                flag.resolved_by_user_id = user.id
                flag.resolved_at = now
                flag.resolution_note = NOTE
                write_audit(
                    session,
                    actor_user_id=user.id,
                    action="quality_resolved",
                    resource_type="data_quality_flag",
                    resource_id=str(flag.id),
                    before=before,
                    after={"status": flag.status, "resolution_note": NOTE},
                    reason="D-064 correction",
                    commit=False,
                )
            session.commit()
        print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

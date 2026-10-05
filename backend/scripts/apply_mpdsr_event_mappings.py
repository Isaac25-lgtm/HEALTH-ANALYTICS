"""Bind the MPDSR event forms to HPIP's approved event fields (D-063, D-068).

Only dates are mapped: the death date from each form and the form's own event date as the
notification or review date. Identifying fields and free text are never mapped, so they are
never stored (``app/domain/mpdsr_minimisation.py`` drops anything unmapped). Coded causes stay
unmapped until an approved cause taxonomy exists.

    python scripts/apply_mpdsr_event_mappings.py --approved-by biostat.pader --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from app.db.session import get_session_factory  # noqa: E402
from app.domain.enums import ActionPermission  # noqa: E402
from app.models import AuditLog, EventFieldMapping, Programme, User  # noqa: E402
from app.services.authorization import require_action, require_programme_access  # noqa: E402
from app.services.sync import EVENT_DATE_SOURCE  # noqa: E402

MAPPING_VERSION = "live-2026-09-21"
REFERENCE = "D-068"

# (event_type, program UID, stage UID, semantic field, source, expected type, required, DHIS2 label)
BINDINGS = (
    (
        "maternal_notification",
        "ZJRDIb1joXP",
        "vdKfzGrAVXa",
        "death_date",
        "qWAqTjmR6Dj",
        "date",
        False,
        "004-DN13 Date and Time of Death (free-text in DHIS2; only a valid date is kept)",
    ),
    (
        "maternal_notification",
        "ZJRDIb1joXP",
        "vdKfzGrAVXa",
        "notification_date",
        EVENT_DATE_SOURCE,
        "date",
        True,
        "HMIS MCH 004 event date: Death Notification Date",
    ),
    (
        "maternal_review",
        "k7i7qPFQV5n",
        "YXed7PnLRco",
        "death_date",
        "WzauwhVOwM0",
        "date",
        False,
        "020-AD06 Date and time of death",
    ),
    (
        "maternal_review",
        "k7i7qPFQV5n",
        "YXed7PnLRco",
        "review_date",
        EVENT_DATE_SOURCE,
        "date",
        True,
        "HMIS MCH 020 event date (labelled 'Date of notification' in DHIS2; owner decision D-068)",
    ),
    (
        "perinatal_notification",
        "gMC8hUMD4Zi",
        "XO582jJT6aP",
        "death_date",
        "lN4hzVULEdF",
        "date",
        False,
        "019-PD17 Date of Death",
    ),
    (
        "perinatal_notification",
        "gMC8hUMD4Zi",
        "XO582jJT6aP",
        "notification_date",
        EVENT_DATE_SOURCE,
        "date",
        True,
        "HMIS MCH 019 event date: Date of notification",
    ),
    (
        "perinatal_review",
        "HjkGOlFiGij",
        "CGz50G2MY16",
        "death_date",
        "Dq9aH0aZ2wb",
        "date",
        False,
        "017-LB04 Date and time of Death",
    ),
    (
        "perinatal_review",
        "HjkGOlFiGij",
        "CGz50G2MY16",
        "review_date",
        EVENT_DATE_SOURCE,
        "date",
        True,
        "HMIS MCH 017 event date: Date of review",
    ),
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--approved-by", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    session = get_session_factory()()
    try:
        approver = session.scalar(select(User).where(User.username == args.approved_by, User.is_active.is_(True)))
        if approver is None:
            raise SystemExit(f"Approver {args.approved_by!r} is not an active user.")
        require_action(session, approver, ActionPermission.MANAGE_MAPPINGS)
        require_programme_access(session, approver, "MPDSR")
        mpdsr = session.scalar(select(Programme).where(Programme.code == "MPDSR"))
        existing = {
            (row.event_type, row.internal_semantic_field): row
            for row in session.scalars(
                select(EventFieldMapping).where(
                    EventFieldMapping.programme_id == mpdsr.id,
                    EventFieldMapping.mapping_version == MAPPING_VERSION,
                )
            ).all()
        }
        created = 0
        for event_type, program, stage, field, source, kind, required, label in BINDINGS:
            if (event_type, field) in existing:
                continue
            session.add(
                EventFieldMapping(
                    programme_id=mpdsr.id,
                    program_uid=program,
                    program_stage_uid=stage,
                    source_data_element_uid=source,
                    internal_semantic_field=field,
                    expected_data_type=kind,
                    required=required,
                    event_type=event_type,
                    mapping_version=MAPPING_VERSION,
                    enabled=True,
                    notes=f"{REFERENCE}: {label}",
                )
            )
            created += 1
        summary = {"mode": "dry_run" if args.dry_run else "applied", "bindings": len(BINDINGS), "created": created}
        if args.dry_run:
            session.rollback()
        else:
            session.add(
                AuditLog(
                    actor_user_id=approver.id,
                    action="event_mappings_applied",
                    resource_type="event_field_mapping",
                    resource_id=str(mpdsr.id),
                    after_json={"reference": REFERENCE, "mapping_version": MAPPING_VERSION, "created": created},
                )
            )
            session.commit()
        print(json.dumps(summary, indent=2))
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())

"""Import DHIS2 sub-counties and health facilities beneath the live districts (D-062, D-068).

Sub-counties (DHIS2 level 5) attach directly to their district/city (level 3); the DHIS2 level-4
DLG/Municipality layer is not modelled (D-062). Facilities (level 6) attach to their sub-county.
Every name, parent and UID comes from DHIS2 metadata retrieved read-only by
``fetch_levels_by_district`` into ``.local/dhis2/org-units-l4-l6.json``. Facility level and
ownership are copied from DHIS2 organisation-unit groups only when exactly one group states them.

Transactional, idempotent and audited: re-running creates no duplicate units or mappings.

    python scripts/import_live_subunits.py --metadata ../.local/dhis2/org-units-l4-l6.json
    python scripts/import_live_subunits.py --metadata ../.local/dhis2/org-units-l4-l6.json --apply \\
        --approved-by biostat.pader --approval-reference "D-062 / D-068"
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from app.db.session import get_session_factory  # noqa: E402
from app.domain.enums import ActionPermission, MappingSourceSystem, OrgUnitLevel  # noqa: E402
from app.models import AuditLog, OrgUnit, OrgUnitMapping, User  # noqa: E402
from app.services.authorization import require_action, require_org_unit_access  # noqa: E402
from app.services.geography import build_path  # noqa: E402
from scripts.import_live_hierarchy import internal_code  # noqa: E402

# DHIS2 organisation-unit groups that state a facility's level, in the order they are reported.
LEVEL_GROUPS = {
    "NRH": "National Referral Hospital",
    "RRH": "Regional Referral Hospital",
    "Specialized Hospital": "Specialized Hospital",
    "General Hospital": "General Hospital",
    "HC IV": "HC IV",
    "HC III": "HC III",
    "HC II": "HC II",
    "Clinic": "Clinic",
    "Drug Shop": "Drug Shop",
}
OWNERSHIP_GROUPS = {"GOV": "Government", "PNFP": "PNFP", "PFP": "PFP"}


def _single(groups: set[str], table: dict[str, str]) -> str | None:
    found = {table[name] for name in groups if name in table}
    return found.pop() if len(found) == 1 else None


def _code(name: str, uid: str) -> str:
    # Sub-county and facility names repeat across districts; the DHIS2 UID keeps the code unique.
    return f"{internal_code(name)[:28]}_{uid}"


def _closed(unit: dict) -> date | None:
    value = unit.get("closedDate")
    return date.fromisoformat(value[:10]) if value else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--approved-by")
    parser.add_argument("--approval-reference")
    args = parser.parse_args(argv)
    if args.apply and not (args.approved_by and args.approval_reference):
        parser.error("--apply requires --approved-by and --approval-reference")

    document = json.loads(args.metadata.read_text(encoding="utf-8"))
    sub_counties, facilities = document["5"], document["6"]
    session = get_session_factory()()
    try:
        mappings = {
            row.external_uid: row.org_unit_id
            for row in session.scalars(
                select(OrgUnitMapping).where(OrgUnitMapping.source_system == MappingSourceSystem.DHIS2.value)
            ).all()
        }
        units = {unit.id: unit for unit in session.scalars(select(OrgUnit)).all()}
        codes = {unit.code for unit in units.values()}
        created = {"sub_county": 0, "facility": 0, "mappings": 0}
        skipped: list[dict] = []

        def add(item: dict, parent: OrgUnit, level: OrgUnitLevel, **extra) -> None:
            uid = item["id"]
            if uid in mappings:
                return
            code = _code(item["name"], uid)
            if code in codes:
                skipped.append({"uid": uid, "reason": "code_collision"})
                return
            closed = _closed(item)
            unit = OrgUnit(
                code=code,
                name=item["name"],
                level_type=level.value,
                parent_id=parent.id,
                path=build_path(parent, code),
                active=closed is None or closed > datetime.now(UTC).date(),
                valid_to=closed,
                **extra,
            )
            session.add(unit)
            session.flush()
            session.add(
                OrgUnitMapping(org_unit_id=unit.id, source_system=MappingSourceSystem.DHIS2.value, external_uid=uid)
            )
            codes.add(code)
            units[unit.id] = unit
            mappings[uid] = unit.id
            created[level.value] += 1
            created["mappings"] += 1

        for item in sorted(sub_counties, key=lambda row: row["path"]):
            segments = item["path"].split("/")
            district_id = mappings.get(segments[3]) if len(segments) > 3 else None
            district = units.get(district_id) if district_id else None
            if district is None or district.level_type not in {OrgUnitLevel.DISTRICT.value, OrgUnitLevel.CITY.value}:
                skipped.append({"uid": item["id"], "reason": "district_not_mapped"})
                continue
            add(item, district, OrgUnitLevel.SUB_COUNTY)

        for item in sorted(facilities, key=lambda row: row["path"]):
            segments = item["path"].split("/")
            parent_id = mappings.get(segments[5]) if len(segments) > 5 else None
            parent = units.get(parent_id) if parent_id else None
            if parent is None or parent.level_type != OrgUnitLevel.SUB_COUNTY.value:
                skipped.append({"uid": item["id"], "reason": "sub_county_not_mapped"})
                continue
            groups = {group["name"] for group in item.get("organisationUnitGroups") or []}
            add(
                item,
                parent,
                OrgUnitLevel.FACILITY,
                facility_level=_single(groups, LEVEL_GROUPS),
                ownership=_single(groups, OWNERSHIP_GROUPS),
            )

        summary = {
            "mode": "applied" if args.apply else "check_only",
            "sub_counties_in_source": len(sub_counties),
            "facilities_in_source": len(facilities),
            "created": created,
            "skipped": len(skipped),
            "skipped_reasons": sorted({item["reason"] for item in skipped}),
        }
        if args.apply:
            approver = session.scalar(select(User).where(User.username == args.approved_by, User.is_active.is_(True)))
            if approver is None:
                raise SystemExit(f"Approver {args.approved_by!r} is not an active user.")
            require_action(session, approver, ActionPermission.MANAGE_MAPPINGS)
            roots = [unit for unit in units.values() if unit.parent_id is None and unit.active]
            if len(roots) != 1 or roots[0].code != "UG":
                raise SystemExit("One approved Uganda root is required.")
            require_org_unit_access(session, approver, roots[0].id)
            session.add(
                AuditLog(
                    actor_user_id=approver.id,
                    action="hierarchy_subunits_imported",
                    resource_type="org_unit",
                    resource_id="levels-5-6",
                    after_json={
                        "approval_reference": args.approval_reference,
                        "source": str(args.metadata),
                        **created,
                        "skipped": len(skipped),
                        "imported_at": datetime.now(UTC).isoformat(),
                    },
                )
            )
            session.commit()
        else:
            session.rollback()
        print(json.dumps(summary, indent=2))
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())

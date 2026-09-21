"""Import Uganda's live DHIS2 hierarchy (levels 1-3) into the HPIP control store.

This copies the national instance's own structure: the country root, its 15 regions and the 146
district/city units, each bound to its DHIS2 UID. Nothing here is invented — every code, name,
parent and UID comes from DHIS2 metadata retrieved read-only by ``scripts/dhis2_discovery.py``.

It is transactional, idempotent and audited. Re-running it makes no duplicate units and no
duplicate mappings. It never touches population, source mappings, geometry or observations.

    python scripts/import_live_hierarchy.py --metadata ../.local/dhis2/org-units-l1-l3.json --check
    python scripts/import_live_hierarchy.py --metadata ../.local/dhis2/org-units-l1-l3.json --apply \
        --approved-by biostat.pader --approval-reference "owner decision 2026-09-21"
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from app.db.session import get_session_factory  # noqa: E402
from app.domain.enums import MappingSourceSystem, OrgUnitLevel  # noqa: E402
from app.models import AuditLog, OrgUnit, OrgUnitMapping, User  # noqa: E402
from app.services.geography import create_org_unit  # noqa: E402

COUNTRY_CODE = "UG"
_NON_CODE = re.compile(r"[^A-Z0-9]+")


def internal_code(name: str) -> str:
    """A stable internal code derived from the DHIS2 name.

    DHIS2 leaves regions and districts without codes, so HPIP needs its own stable identifier.
    The DHIS2 UID remains the authoritative external key; this is only the local handle.
    """
    # The unit type must stay in the code: Uganda has both "Arua District" and "Arua City", and
    # stripping the type collapses ten such pairs into a single unit each.
    return _NON_CODE.sub("_", name.strip().upper()).strip("_")[:40]


def level_for(name: str) -> OrgUnitLevel:
    """DHIS2 level 3 mixes districts and cities; the unit's own name states which it is."""
    return OrgUnitLevel.CITY if name.strip().lower().endswith("city") else OrgUnitLevel.DISTRICT


def load_units(path: Path) -> tuple[dict, list[dict], list[dict]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    items = document["resources"]["org-units"]["items"]
    by_level: dict[int, list[dict]] = {}
    for unit in items:
        by_level.setdefault(int(unit["level"]), []).append(unit)
    roots = by_level.get(1, [])
    if len(roots) != 1:
        raise SystemExit(f"Expected exactly one DHIS2 level-1 root, found {len(roots)}.")
    regions = sorted(by_level.get(2, []), key=lambda u: u["name"])
    districts = sorted(by_level.get(3, []), key=lambda u: u["name"])
    return roots[0], regions, districts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--apply", action="store_true", help="Commit. Without it, nothing is written.")
    parser.add_argument("--check", action="store_true", default=True)
    parser.add_argument("--approved-by", help="Username of the authorised approver (required for --apply).")
    parser.add_argument("--approval-reference", help="Owner decision reference (required for --apply).")
    args = parser.parse_args(argv)

    if args.apply and not (args.approved_by and args.approval_reference):
        parser.error("--apply requires --approved-by and --approval-reference")

    dhis2_root, regions, districts = load_units(args.metadata)
    session = get_session_factory()()
    try:
        country = session.scalar(
            select(OrgUnit).where(OrgUnit.code == COUNTRY_CODE, OrgUnit.parent_id.is_(None))
        )
        if country is None:
            raise SystemExit("The neutral HPIP country root 'UG' is missing; run the reference bootstrap first.")

        approver = None
        if args.apply:
            approver = session.scalar(select(User).where(User.username == args.approved_by))
            if approver is None or not approver.is_active:
                raise SystemExit(f"Approver {args.approved_by!r} is not an active user.")

        existing_units = {
            unit.code: unit for unit in session.scalars(select(OrgUnit)).all()
        }
        existing_uids = {
            row.external_uid: row
            for row in session.scalars(
                select(OrgUnitMapping).where(
                    OrgUnitMapping.source_system == MappingSourceSystem.DHIS2.value
                )
            ).all()
        }

        created_units = 0
        created_mappings = 0

        def ensure_mapping(unit: OrgUnit, uid: str) -> None:
            nonlocal created_mappings
            if uid in existing_uids:
                return
            session.add(
                OrgUnitMapping(
                    org_unit_id=unit.id,
                    source_system=MappingSourceSystem.DHIS2.value,
                    external_uid=uid,
                )
            )
            created_mappings += 1

        # 1. Bind the existing neutral root to the live national root.
        ensure_mapping(country, dhis2_root["id"])

        # 2. Regions, then 3. districts/cities beneath their own region.
        region_by_uid: dict[str, OrgUnit] = {}
        for region in regions:
            code = internal_code(region["name"])
            unit = existing_units.get(code)
            if unit is None:
                unit = create_org_unit(
                    session, code=code, name=region["name"], level_type=OrgUnitLevel.REGION, parent=country
                )
                existing_units[code] = unit
                created_units += 1
            region_by_uid[region["id"]] = unit
            ensure_mapping(unit, region["id"])

        for district in districts:
            parent_uid = (district.get("parent") or {}).get("id")
            parent = region_by_uid.get(parent_uid, country)
            code = internal_code(district["name"])
            unit = existing_units.get(code)
            if unit is None:
                unit = create_org_unit(
                    session,
                    code=code,
                    name=district["name"],
                    level_type=level_for(district["name"]),
                    parent=parent,
                )
                existing_units[code] = unit
                created_units += 1
            ensure_mapping(unit, district["id"])

        session.flush()

        peers = session.scalars(
            select(OrgUnit).where(
                OrgUnit.level_type.in_([OrgUnitLevel.DISTRICT.value, OrgUnitLevel.CITY.value]),
                OrgUnit.active.is_(True),
            )
        ).all()
        summary = {
            "mode": "applied" if args.apply else "check_only",
            "dhis2_root": {"uid": dhis2_root["id"], "name": dhis2_root["name"]},
            "regions_in_source": len(regions),
            "districts_and_cities_in_source": len(districts),
            "org_units_created": created_units,
            "dhis2_mappings_created": created_mappings,
            "active_district_city_peers": len(peers),
            "cities": sum(1 for unit in peers if unit.level_type == OrgUnitLevel.CITY.value),
            "districts": sum(1 for unit in peers if unit.level_type == OrgUnitLevel.DISTRICT.value),
        }

        if args.apply:
            session.add(
                AuditLog(
                    actor_user_id=approver.id,
                    action="hierarchy_imported",
                    resource_type="org_unit",
                    resource_id=str(country.id),
                    after_json={
                        "approval_reference": args.approval_reference,
                        "approved_by": approver.username,
                        "source": str(args.metadata),
                        "dhis2_root_uid": dhis2_root["id"],
                        "org_units_created": created_units,
                        "dhis2_mappings_created": created_mappings,
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

"""Apply owner-confirmed DHIS2 source mappings for the HPIP indicator source keys.

Each row binds one internal source key to one DHIS2 data element, identified by the element's
own HMIS code in the national instance (for example ``ANC1`` -> ``105-AN01a. ANC 1st Visit for
women``). The UID is resolved from retrieved metadata at run time, so no UID is written by hand.

Keys that have no unambiguous element in this instance are deliberately absent. They stay
unmapped and their indicators remain unavailable rather than being bound to an approximation.

    python scripts/import_source_mappings.py --metadata ../.local/dhis2/metadata-full.json --check
    python scripts/import_source_mappings.py --metadata ../.local/dhis2/metadata-full.json --apply \
        --approved-by biostat.pader --approval-reference "owner decision 2026-09-21"
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from app.db.session import get_session_factory  # noqa: E402
from app.models import AuditLog, Programme, SourceMapping, User  # noqa: E402

MAPPING_VERSION = "live-2026-09-21"

# internal source key -> (programme code, DHIS2 data element code in the national instance)
CONFIRMED: dict[str, tuple[str, str]] = {
    # Antenatal care
    "ANC1": ("MNCH", "105-AN01A"),
    "ANC1_FT": ("MNCH", "105-AN01b"),
    "ANC4": ("MNCH", "105-AN02"),
    "ANC8": ("MNCH", "105-AN03"),
    "IPT3": ("MNCH", "105-AN06C"),
    "HB_TESTED": ("MNCH", "105-AN08"),
    "ULTRASOUND": ("MNCH", "105-AN12A"),
    "IFA_30": ("MNCH", "105-AN10B"),
    # 108-SP01 is the aggregate caesarean total. The 020-DP15/DP16 pair the owner first approved
    # is TRACKER/TRUE_ONLY and returned zero in all 146 districts for June 2025, so it failed the
    # owner's own "numeric counts at compatible geography and period" validation.
    "CS": ("MNCH", "108-SP01"),
    # Delivery and newborn
    "DELIVERIES": ("MNCH", "105-MA04"),
    "LIVE_BIRTHS": ("MNCH", "105-MA05A1"),
    "FRESH_SB": ("MNCH", "105-MA05B1"),
    "MACERATED_SB": ("MNCH", "105-MA05C1"),
    "MATERNAL_DEATHS": ("MNCH", "105-MA13"),
    "NEWBORN_DEATHS": ("MNCH", "105-MA12"),
    "BIRTH_ASPHYXIA": ("MNCH", "105-MA23"),
    "RESUSCITATED": ("MNCH", "105-MA24"),
    "KMC_PERCENT": ("MNCH", "105-MA08"),
    # Immunisation: Uganda's HMIS 105 child-health series
    "BCG": ("EPI", "105-CL01"),
    "HEPB_BIRTH": ("EPI", "105-CL02"),
    "OPV0": ("EPI", "105-CL04"),
    "OPV1": ("EPI", "105-CL05"),
    "OPV2": ("EPI", "105-CL06"),
    "OPV3": ("EPI", "105-CL07"),
    "IPV1": ("EPI", "105-CL08"),
    "IPV2": ("EPI", "105-CL09."),
    "PENTA1": ("EPI", "105-CL10"),
    "PENTA2": ("EPI", "105-CL11"),
    "PENTA3": ("EPI", "105-CL12"),
    "PCV1": ("EPI", "105-CL13."),
    "PCV2": ("EPI", "105-CL14."),
    "PCV3": ("EPI", "105-CL15."),
    "ROTAV1": ("EPI", "105-CL16"),
    "ROTAV2": ("EPI", "105-CL17"),
    "MV1": ("EPI", "105-CL19."),
    "MV2": ("EPI", "105-CL20."),
    "MV3": ("EPI", "105-CL21"),
    "MV4": ("EPI", "105-CL26"),
    "YF": ("EPI", "105-CL22"),
    "MR": ("EPI", "105-CL23"),
    "HPV": ("EPI", "105-VP01"),
    "VITA_12_59": ("EPI", "097C-VH15"),
}

# Keys that are a category slice of one element rather than an element of their own.
# The category option UID is resolved live from the element's own category combination.
CONFIRMED_WITH_CATEGORY: dict[str, tuple[str, str, str]] = {
    "ANC1_AGE_LT15": ("MNCH", "105-AN01A", "<15Yrs"),
    "ANC1_AGE_15_19": ("MNCH", "105-AN01A", "15-19Yrs"),
}

# Deliberately unmapped: no unambiguous element exists in this instance. Indicators depending on
# these remain unavailable, which is correct, rather than bound to an approximation.
WITHHELD = {
    "TD_1549": "available elements are ANC TD1/TD2/TD3 or protection at birth, not women aged 15-49",
    "DEWORM_1_14": "instance reports 6-59 months and under-five, not ages 1-14",
    "VITA_6_11": "no 6-11 month vitamin A element exists in this instance",
    "UNDER5": "available element is an under-five child count, not a service/dose numerator",
}


def resolve_category_option(element_uid: str, option_name: str) -> str:
    """Resolve one category option combination UID from the live instance.

    The option is looked up on the element's own category combination, so the identifier always
    comes from live metadata rather than being written by hand.
    """
    from app.config import get_settings
    from app.integrations.dhis2.http import Dhis2HttpClient

    settings = get_settings()
    prefix = settings.dhis2_api_path_prefix.rstrip("/")
    with Dhis2HttpClient(settings) as client:
        payload = client.get_json(
            f"{prefix}/dataElements/{element_uid}",
            params={"fields": "categoryCombo[name,categoryOptionCombos[id,name]]"},
        )
    combos = (payload.get("categoryCombo") or {}).get("categoryOptionCombos") or []
    matches = [combo for combo in combos if str(combo.get("name", "")).strip() == option_name]
    if len(matches) != 1:
        raise SystemExit(
            f"Category option {option_name!r} matched {len(matches)} combinations on {element_uid}."
        )
    return matches[0]["id"]


def element_index(metadata_path: Path) -> dict[str, dict]:
    document = json.loads(metadata_path.read_text(encoding="utf-8"))
    index: dict[str, dict] = {}
    for element in document["resources"]["data-elements"]["items"]:
        code = str(element.get("code") or "").strip()
        if code:
            index[code.upper()] = element
    return index


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--approved-by")
    parser.add_argument("--approval-reference")
    parser.add_argument("--mapping-version", default=MAPPING_VERSION)
    args = parser.parse_args(argv)
    if args.apply and not (args.approved_by and args.approval_reference):
        parser.error("--apply requires --approved-by and --approval-reference")

    elements = element_index(args.metadata)
    unresolved = [key for key, (_, code) in CONFIRMED.items() if code.upper() not in elements]
    if unresolved:
        print(json.dumps({"mode": "blocked", "unresolved_codes": unresolved}, indent=2))
        return 3

    session = get_session_factory()()
    try:
        programmes = {p.code: p for p in session.scalars(select(Programme)).all()}
        approver = None
        if args.apply:
            approver = session.scalar(select(User).where(User.username == args.approved_by))
            if approver is None or not approver.is_active:
                raise SystemExit(f"Approver {args.approved_by!r} is not an active user.")

        existing = {
            (row.internal_source_key, row.mapping_version)
            for row in session.scalars(
                select(SourceMapping).where(SourceMapping.mapping_version == args.mapping_version)
            ).all()
        }
        created = 0
        rows = []
        for key in sorted(CONFIRMED):
            programme_code, element_code = CONFIRMED[key]
            element = elements[element_code.upper()]
            programme = programmes.get(programme_code)
            if programme is None:
                raise SystemExit(f"Programme {programme_code!r} is not configured.")
            rows.append(
                {
                    "source_key": key,
                    "programme": programme_code,
                    "dhis2_code": element.get("code"),
                    "dhis2_uid": element["id"],
                    "dhis2_name": element.get("name"),
                }
            )
            if (key, args.mapping_version) in existing:
                continue
            session.add(
                SourceMapping(
                    internal_source_key=key,
                    programme_id=programme.id,
                    dhis2_item_uid=element["id"],
                    item_kind="data_element",
                    aggregation_semantics="SUM",
                    mapping_version=args.mapping_version,
                    enabled=True,
                )
            )
            created += 1

        for key in sorted(CONFIRMED_WITH_CATEGORY):
            programme_code, element_code, option_name = CONFIRMED_WITH_CATEGORY[key]
            element = elements[element_code.upper()]
            programme = programmes[programme_code]
            option_uid = resolve_category_option(element["id"], option_name)
            rows.append(
                {
                    "source_key": key,
                    "programme": programme_code,
                    "dhis2_code": element.get("code"),
                    "dhis2_uid": element["id"],
                    "dhis2_name": element.get("name"),
                    "category_option_combo": option_name,
                    "category_option_combo_uid": option_uid,
                }
            )
            if (key, args.mapping_version) in existing:
                continue
            session.add(
                SourceMapping(
                    internal_source_key=key,
                    programme_id=programme.id,
                    dhis2_item_uid=element["id"],
                    category_option_combo_uid=option_uid,
                    item_kind="data_element",
                    aggregation_semantics="SUM",
                    mapping_version=args.mapping_version,
                    enabled=True,
                )
            )
            created += 1
        session.flush()

        summary = {
            "mode": "applied" if args.apply else "check_only",
            "mapping_version": args.mapping_version,
            "confirmed_keys": len(CONFIRMED) + len(CONFIRMED_WITH_CATEGORY),
            "mappings_created": created,
            "withheld_keys": sorted(WITHHELD),
            "withheld_count": len(WITHHELD),
            "rows": rows,
        }
        if args.apply:
            session.add(
                AuditLog(
                    actor_user_id=approver.id,
                    action="source_mappings_applied",
                    resource_type="source_mapping",
                    resource_id=args.mapping_version,
                    after_json={
                        "approval_reference": args.approval_reference,
                        "approved_by": approver.username,
                        "mapping_version": args.mapping_version,
                        "mappings_created": created,
                        "withheld_keys": sorted(WITHHELD),
                        "applied_at": datetime.now(UTC).isoformat(),
                    },
                )
            )
            session.commit()
        else:
            session.rollback()
        print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, indent=2))
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())

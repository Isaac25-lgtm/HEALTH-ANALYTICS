"""Report what the live mapping set covers, and which indicators each gap makes unavailable.

Reads the control store only. It never contacts DHIS2 and never changes configuration, so it is
safe to run against the live database at any time.

    python scripts/mapping_coverage_report.py --mapping-version live-2026-09-21
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
from app.domain.indicator_catalog import INDICATOR_CATALOG  # noqa: E402
from app.models import Programme, SourceMapping  # noqa: E402
from app.services.mapping_coverage import _source_keys_of, required_source_keys  # noqa: E402


def indicators_depending_on(key: str) -> list[str]:
    affected = []
    for indicator in INDICATOR_CATALOG:
        keys: set[str] = set()
        _source_keys_of(indicator.get("formula_spec"), keys)
        if key in keys:
            affected.append(indicator["code"])
    return sorted(affected)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mapping-version", required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    session = get_session_factory()()
    try:
        programmes = {p.id: p.code for p in session.scalars(select(Programme)).all()}
        rows = session.scalars(
            select(SourceMapping).where(SourceMapping.mapping_version == args.mapping_version)
        ).all()
        mapped = []
        for row in sorted(rows, key=lambda r: r.internal_source_key):
            mapped.append(
                {
                    "source_key": row.internal_source_key,
                    "programme": programmes.get(row.programme_id),
                    "dhis2_uid": row.dhis2_item_uid,
                    "category_option_combo_uid": row.category_option_combo_uid,
                    "operand": (
                        f"{row.dhis2_item_uid}.{row.category_option_combo_uid}"
                        if row.category_option_combo_uid
                        else row.dhis2_item_uid
                    ),
                    "item_kind": row.item_kind,
                    "aggregation_semantics": row.aggregation_semantics,
                    "enabled": row.enabled,
                    "valid_from": row.valid_from.isoformat() if row.valid_from else None,
                    "valid_to": row.valid_to.isoformat() if row.valid_to else None,
                }
            )
        mapped_keys = {item["source_key"] for item in mapped}
        withheld = {}
        for programme_code in ("MNCH", "EPI", "MPDSR"):
            for key in sorted(required_source_keys(programme_code) - mapped_keys):
                withheld.setdefault(
                    key, {"programmes": [], "indicators_unavailable": indicators_depending_on(key)}
                )["programmes"].append(programme_code)

        by_programme = {}
        for programme_code in ("MNCH", "EPI", "MPDSR"):
            required = required_source_keys(programme_code)
            by_programme[programme_code] = {
                "required": len(required),
                "mapped": len(required & mapped_keys),
                "withheld": sorted(required - mapped_keys),
            }

        report = {
            "mapping_version": args.mapping_version,
            "mapped_count": len(mapped),
            "withheld_count": len(withheld),
            "by_programme": by_programme,
            "mapped": mapped,
            "withheld": withheld,
        }
        document = json.dumps(report, indent=2, sort_keys=True)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(document + "\n", encoding="utf-8")
        print(
            json.dumps(
                {
                    "mapping_version": args.mapping_version,
                    "mapped_count": report["mapped_count"],
                    "withheld_count": report["withheld_count"],
                    "by_programme": by_programme,
                    "withheld": {k: v["indicators_unavailable"] for k, v in withheld.items()},
                    "output": str(args.out) if args.out else "stdout",
                },
                indent=2,
            )
        )
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())

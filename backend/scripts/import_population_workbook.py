"""Verify, reconcile, stage (default) or apply the owner-supplied district/city population workbook.

Usage (from backend/):
    python scripts/import_population_workbook.py                       # verify + reconcile, print report
    python scripts/import_population_workbook.py --write-reports       # also write docs/reconciliation/*
    python scripts/import_population_workbook.py --stage --username <importer>
    python scripts/import_population_workbook.py --apply --version-code UBOS_DC_2024_2030 --username <importer>

The workbook is only ever read, and its checksum is verified before and after reading.

`--stage` preserves all 146 source rows and every match state without creating a denominator;
it is the safe step while the authoritative organisation-unit hierarchy is unavailable.
`--apply` creates DRAFT population versions only, and only when the reconciliation is clean;
approval remains a separate, audited step by a different user.
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from app.db.session import get_session_factory  # noqa: E402
from app.models import User  # noqa: E402
from app.services.authorization import AuthorizationError  # noqa: E402
from app.services.population_workbook import (  # noqa: E402
    REFERENCE_AUTHORITATIVE,
    REFERENCE_UNAPPROVED,
    VERIFIED_SHA256,
    PopulationWorkbookError,
    apply_population_workbook,
    crosswalk_semantics,
    derived_national_totals,
    detect_reference_scope,
    read_population_workbook,
    reconcile_workbook,
    region_totals,
    stage_population_workbook,
    staging_summary,
    structure_findings,
)

DEFAULT_WORKBOOK = REPO / "Uganda_District_City_Populations_2024_2030.xlsx"
# The owner refers to this file as "...(1).xlsx"; the repository copy has no suffix. Both names
# are recorded so provenance matches the instruction that supplied it.
OWNER_DISPLAY_NAME = "Uganda_District_City_Populations_2024_2030 (1).xlsx"
REPORT_DIR = REPO / "docs" / "reconciliation"


def _markdown(payload: dict) -> str:
    workbook = payload["workbook"]
    counts = payload["counts"]
    scope_notes = {
        REFERENCE_AUTHORITATIVE: "matched against an authoritative, owner-approved organisation-unit hierarchy",
        REFERENCE_UNAPPROVED: "matched against a full organisation-unit cohort whose approval has not been "
        "recorded, so **no match below is a production mapping**",
    }
    scope_note = scope_notes.get(
        payload["reference_scope"],
        "matched only against synthetic development fixtures, so **no match below is a production mapping**",
    )
    lines = [
        "# Population workbook reconciliation",
        "",
        f"Generated {payload['generated_at']} by `scripts/import_population_workbook.py` "
        f"({payload['importer_version']}). Read-only: the workbook was not modified.",
        "",
        "## Source identity",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Owner-supplied display name | `{payload['source_display_name']}` |",
        f"| Filesystem name | `{workbook['file_name']}` |",
        f"| SHA-256 | `{workbook['sha256']}` |",
        f"| Checksum verified | {workbook['checksum_verified']} |",
        f"| Sheet | `{workbook['sheet']}` |",
        f"| Administrative units | {workbook['unit_rows']} ({workbook['districts']} districts, "
        f"{workbook['cities']} cities) |",
        f"| Years | {', '.join(str(year) for year in workbook['years'])} |",
        f"| Population cells | {workbook['cells']} |",
        "",
        "## Structure validation",
        "",
    ]
    if payload["structure_findings"]:
        lines.extend(f"- {item}" for item in payload["structure_findings"])
    else:
        lines.append("- No differences from the expected structure (135 districts + 11 cities, 2024-2030).")
    lines.extend(
        [
            "",
            "## Derived national totals",
            "",
            "National population is **derived** as the sum of the 146 district and city rows and "
            "compared with the workbook's own total row. It is never hard-coded.",
            "",
            "| Year | Derived total | Workbook total row | Match |",
            "|---|---|---|---|",
        ]
    )
    for year in workbook["years"]:
        derived = payload["derived_national_totals"].get(str(year))
        stated = workbook["national_total"]["values"].get(str(year))
        lines.append(f"| {year} | {derived:,} | {int(stated):,} | {'yes' if str(derived) == str(stated) else 'NO'} |")
    header = "| Region | " + " | ".join(str(year) for year in workbook["years"]) + " |"
    lines.extend(["", "## Broad-region totals", "", header])
    lines.append("|---" * (len(workbook["years"]) + 1) + "|")
    for region, values in payload["region_totals"].items():
        cells = " | ".join(f"{values.get(str(year), 0):,}" for year in workbook["years"])
        lines.append(f"| {region} | {cells} |")
    lines.extend(
        [
            "",
            "Regions are the workbook's four broad statistical regions. They are descriptive "
            "metadata for reconciliation only, never an analytical parent, and never health "
            "sub-regions. Health sub-region totals are not calculated because no approved "
            "membership mapping exists.",
            "",
            "## Organisation-unit crosswalk",
            "",
            f"Candidate matches were {scope_note}.",
            "",
            "| Match state | Units |",
            "|---|---|",
        ]
    )
    for state, count in counts.items():
        lines.append(f"| `{state}` | {count} |")
    lines.extend(
        [
            "",
            "| Measure | Units |",
            "|---|---|",
            f"| Reconciliation matched (exact or approved alias) | {payload['reconciliation_matched']} |",
            f"| Reconciliation unmatched | {payload['reconciliation_unmatched']} |",
            f"| Production resolved | {payload['production_resolved']} |",
            f"| **Production unresolved** | **{payload['production_unresolved']}** of {workbook['unit_rows']} |",
            "",
            "Only a match against an authoritative, owner-approved hierarchy reduces production-unresolved "
            "units. Reconciliation matches against anything else are candidates only.",
            "",
        ]
    )
    if payload["non_production_candidates"]:
        lines.extend(
            [
                "### Non-production candidates",
                "",
                "These names matched synthetic or unapproved organisation units. They are **not** production "
                "mappings and create no denominator.",
                "",
                "| Row | Source unit | Type | Matched state | Candidate organisation unit |",
                "|---|---|---|---|---|",
            ]
        )
        for item in payload["non_production_candidates"]:
            lines.append(
                f"| {item['row_number']} | {item['source_unit_name']} | {item['source_unit_type']} | "
                f"`{item['status']}` (non-production candidate) | {item['org_unit_name'] or ''} |"
            )
        lines.append("")
    lines.extend(
        [
            "### Units needing an explicit decision",
            "",
            "| Row | Source unit | Type | Region | State | Detail |",
            "|---|---|---|---|---|---|",
        ]
    )
    for item in payload["attention"][:200]:
        lines.append(
            f"| {item['row_number']} | {item['source_unit_name']} | {item['source_unit_type']} | "
            f"{item['source_region'] or ''} | `{item['status']}` | {item['detail'] or ''} |"
        )
    if len(payload["attention"]) > 200:
        lines.append(f"| … | {len(payload['attention']) - 200} more in the JSON report | | | | |")
    lines.extend(
        [
            "",
            "### Named units the owner asked us to watch",
            "",
            "| Source unit | State | Candidate organisation unit | Note |",
            "|---|---|---|---|",
        ]
    )
    for item in payload["watchlist"]:
        lines.append(
            f"| {item['source_unit_name']} | `{item['status']}` | {item['org_unit_name'] or '—'} | "
            f"{item['detail'] or 'Awaiting an explicit owner decision.'} |"
        )
    lines.extend(
        [
            "",
            "## Rules that still apply",
            "",
            "- No alias is approved because two names look similar; each needs a recorded decision "
            "by a second reviewer.",
            "- Staged rows are not denominators. Applying creates DRAFT versions only, and approval "
            "is a separate audited step.",
            "- Sub-county and facility populations are never derived from this workbook.",
            "",
        ]
    )
    return "\n".join(lines)


def _payload(session, report, *, display_name: str) -> dict:
    extract = report.extract
    base = report.as_dict(mode="reconcile")
    watch_terms = ("kampala", "gulu", "manaf")
    units = base["units"]
    attention = [item for item in units if item["status"] not in {"matched_exact", "matched_alias"}]
    scope = detect_reference_scope(session)
    semantics = crosswalk_semantics(report, scope)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "importer_version": base.get("importer_version", "hpip-population-workbook-2"),
        "source_display_name": display_name,
        "source_dataset": base["source_dataset"],
        "workbook": base["workbook"],
        "counts": base["counts"],
        "structure_findings": structure_findings(extract),
        "derived_national_totals": derived_national_totals(extract),
        "region_totals": region_totals(extract),
        "health_sub_region_totals": {
            "status": "not_calculated",
            "reason": "No approved health sub-region membership mapping exists for these units.",
        },
        "reference_scope": scope,
        "reconciliation_matched": semantics["reconciliation_matched"],
        "reconciliation_unmatched": semantics["reconciliation_unmatched"],
        "production_resolved": semantics["production_resolved"],
        "production_unresolved": semantics["production_unresolved"],
        "non_production_candidates": semantics["non_production_candidates"],
        "attention": attention,
        "watchlist": [
            item for item in units if any(term in item["source_unit_name"].lower() for term in watch_terms)
        ],
        "units": units,
        "lower_levels": base["lower_levels"],
        "national_total_handling": base["national_total_handling"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workbook", type=Path, default=DEFAULT_WORKBOOK)
    parser.add_argument("--expected-sha256", default=VERIFIED_SHA256)
    parser.add_argument("--report", type=Path, help="Write the JSON reconciliation report to this path.")
    parser.add_argument(
        "--write-reports",
        action="store_true",
        help="Write docs/reconciliation/POPULATION_RECONCILIATION.{md,json}.",
    )
    parser.add_argument(
        "--stage",
        action="store_true",
        help="Record every source row and match state in a governed import batch (no denominator).",
    )
    parser.add_argument("--apply", action="store_true", help="Create DRAFT versions after a clean reconciliation.")
    parser.add_argument("--version-code")
    parser.add_argument("--username", help="Importing user (needs the population permission).")
    parser.add_argument("--display-name", default=OWNER_DISPLAY_NAME)
    parser.add_argument("--include-national-total", action="store_true")
    parser.add_argument("--national-org-unit-code")
    args = parser.parse_args(argv)
    warnings.filterwarnings("ignore", module="openpyxl")

    session = get_session_factory()()
    try:
        extract = read_population_workbook(args.workbook, expected_sha256=args.expected_sha256)
        report = reconcile_workbook(session, extract)
        payload = _payload(session, report, display_name=args.display_name)
        summary = {
            "mode": "apply" if args.apply else ("stage" if args.stage else "dry_run"),
            "can_apply": report.can_apply,
        }
        summary |= {
            key: payload[key]
            for key in (
                "source_display_name",
                "workbook",
                "counts",
                "structure_findings",
                "derived_national_totals",
                "region_totals",
                "reference_scope",
                "reconciliation_unmatched",
                "production_unresolved",
            )
        }
        if args.stage or args.apply:
            if not args.username:
                raise PopulationWorkbookError("arguments_required", "--stage and --apply need --username.")
            user = session.scalar(select(User).where(User.username == args.username))
            if user is None:
                raise PopulationWorkbookError("unknown_user", "The importing user does not exist.")
        if args.stage:
            outcome = stage_population_workbook(
                session,
                user,
                report=report,
                source_display_name=args.display_name,
                notes="Staged by scripts/import_population_workbook.py --stage",
            )
            session.commit()
            summary["staged_batch"] = staging_summary(session, outcome.batch)
            summary["staged_batch"]["reused_existing_batch"] = outcome.reused
        if args.apply:
            if not args.version_code:
                raise PopulationWorkbookError("arguments_required", "--apply needs --version-code.")
            versions = apply_population_workbook(
                session,
                user,
                args.workbook,
                version_code=args.version_code,
                expected_sha256=args.expected_sha256,
                include_national_total=args.include_national_total,
                national_org_unit_code=args.national_org_unit_code,
            )
            session.commit()
            summary["created_versions"] = [
                {"id": str(item.id), "code": item.code, "approval_status": item.approval_status} for item in versions
            ]
        if not (args.stage or args.apply):
            session.rollback()
        if args.report:
            args.report.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        if args.write_reports:
            REPORT_DIR.mkdir(parents=True, exist_ok=True)
            (REPORT_DIR / "POPULATION_RECONCILIATION.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
            (REPORT_DIR / "POPULATION_RECONCILIATION.md").write_text(_markdown(payload), encoding="utf-8")
            summary["reports_written"] = [
                str((REPORT_DIR / "POPULATION_RECONCILIATION.json").relative_to(REPO)),
                str((REPORT_DIR / "POPULATION_RECONCILIATION.md").relative_to(REPO)),
            ]
        print(json.dumps(summary, indent=2))
        return 0 if (report.can_apply or not args.apply) else 2
    except (PopulationWorkbookError, AuthorizationError) as error:
        session.rollback()
        print(json.dumps({"error": getattr(error, "code", "error"), "message": str(error)}, indent=2))
        return 2
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())

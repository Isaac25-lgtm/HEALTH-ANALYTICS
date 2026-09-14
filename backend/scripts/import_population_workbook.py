"""Dry-run (default) or apply the owner-supplied district/city population workbook.

Usage (from backend/):
    python scripts/import_population_workbook.py                      # dry run, prints the reconciliation
    python scripts/import_population_workbook.py --report out.json    # dry run, also writes the report
    python scripts/import_population_workbook.py --apply --version-code UBOS_DC_2024_2030 --username <importer>

The workbook is only read. Its checksum is verified before reading. Apply creates DRAFT
versions only; approval is a separate, audited step by a different user.
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from app.db.session import get_session_factory  # noqa: E402
from app.models import User  # noqa: E402
from app.services.authorization import AuthorizationError  # noqa: E402
from app.services.population_workbook import (  # noqa: E402
    VERIFIED_SHA256,
    PopulationWorkbookError,
    apply_population_workbook,
    read_population_workbook,
    reconcile_workbook,
)

DEFAULT_WORKBOOK = REPO / "Uganda_District_City_Populations_2024_2030.xlsx"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workbook", type=Path, default=DEFAULT_WORKBOOK)
    parser.add_argument("--expected-sha256", default=VERIFIED_SHA256)
    parser.add_argument("--report", type=Path, help="Also write the JSON reconciliation report to this path.")
    parser.add_argument("--apply", action="store_true", help="Create DRAFT versions after a clean reconciliation.")
    parser.add_argument("--version-code")
    parser.add_argument("--username", help="Importing user (needs edit_population).")
    parser.add_argument("--include-national-total", action="store_true")
    parser.add_argument("--national-org-unit-code")
    args = parser.parse_args(argv)
    warnings.filterwarnings("ignore", module="openpyxl")

    session = get_session_factory()()
    try:
        extract = read_population_workbook(args.workbook, expected_sha256=args.expected_sha256)
        report = reconcile_workbook(session, extract)
        output = report.as_dict(mode="apply" if args.apply else "dry_run")
        if not args.report:
            output.pop("units")
        if args.apply:
            if not args.version_code or not args.username:
                raise PopulationWorkbookError("arguments_required", "--apply needs --version-code and --username.")
            user = session.scalar(select(User).where(User.username == args.username))
            if user is None:
                raise PopulationWorkbookError("unknown_user", "The importing user does not exist.")
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
            output["created_versions"] = [
                {"id": str(item.id), "code": item.code, "approval_status": item.approval_status} for item in versions
            ]
        else:
            session.rollback()
        if args.report:
            args.report.write_text(json.dumps(report.as_dict(mode=output["mode"]), indent=2), encoding="utf-8")
        print(json.dumps(output, indent=2))
        return 0 if report.can_apply or not args.apply else 2
    except (PopulationWorkbookError, AuthorizationError) as error:
        session.rollback()
        print(json.dumps({"error": getattr(error, "code", "error"), "message": str(error)}, indent=2))
        return 2
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())

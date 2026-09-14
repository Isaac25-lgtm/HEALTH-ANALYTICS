"""Validate and, when explicitly requested, import owner-supplied map boundaries."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from sqlalchemy import select

from app.db.session import get_session_factory
from app.models import User
from app.services.authorization import AuthorizationError
from app.services.geometry import GeometryImportError, apply_geometry_import, prepare_geometry_import


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Dry-run is the default. Applying requires a database user with manage_mappings, "
            "an explicit validity date, and a complete organisation-unit master."
        )
    )
    parser.add_argument("path", type=Path)
    parser.add_argument("--level", choices=["district", "sub_county"], required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--user", help="Username recorded as the audited importer.")
    parser.add_argument("--valid-from", type=date.fromisoformat)
    parser.add_argument("--allow-unmatched", action="store_true")
    parser.add_argument(
        "--effective-date-verified",
        action="store_true",
        help="Confirm the owner verified the boundary effective date. Required to apply.",
    )
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    factory = get_session_factory()
    with factory() as session:
        try:
            plan = prepare_geometry_import(session, args.path, args.level)
            output = {"mode": "apply" if args.apply else "dry_run", **plan.summary()}
            if args.apply:
                if not args.user or not args.valid_from:
                    raise GeometryImportError("--apply requires --user and --valid-from.")
                if not args.effective_date_verified:
                    raise GeometryImportError(
                        "--apply requires --effective-date-verified: the owner must confirm the "
                        "boundary effective date before geometry is activated."
                    )
                user = session.scalar(
                    select(User).where(User.username == args.user, User.is_active.is_(True))
                )
                if user is None:
                    raise GeometryImportError("The audited importing user was not found or is inactive.")
                output["result"] = apply_geometry_import(
                    session,
                    user,
                    plan,
                    valid_from=args.valid_from,
                    allow_unmatched=args.allow_unmatched,
                    effective_date_verified=args.effective_date_verified,
                )
                session.commit()
            print(json.dumps(output, indent=2))
            return 0
        except (GeometryImportError, AuthorizationError) as exc:
            session.rollback()
            print(json.dumps({"status": "failed", "message": str(exc)}, indent=2))
            return 1


if __name__ == "__main__":
    raise SystemExit(main())

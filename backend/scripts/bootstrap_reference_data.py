"""Create the approved, non-secret reference configuration on a migrated database.

Release order: ``alembic upgrade head`` -> this command -> ``create_initial_admin.py`` (once).

It creates programmes, roles and action permissions, the versioned indicator catalogue, the
quality-rule catalogue, the owner-approved D-045 population-period rules and the neutral
country root. It never creates users, sub-national geography, DHIS2 UIDs, raw values,
population values or boundaries. Safe to run on every release and under concurrent releases.

Exit codes: 0 success (created or already present), 2 refused (invalid configuration or the
database is not at the Alembic head), 3 existing configuration conflicts with the reference
(nothing written).

Usage:
    python scripts/bootstrap_reference_data.py            # apply
    python scripts/bootstrap_reference_data.py --check    # report only, writes nothing
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from alembic.config import Config  # noqa: E402
from alembic.script import ScriptDirectory  # noqa: E402
from sqlalchemy import inspect, text  # noqa: E402

from app.config import get_settings, validate_runtime_settings  # noqa: E402
from app.db.session import get_session_factory  # noqa: E402
from app.services.reference_bootstrap import ReferenceBootstrapConflict, bootstrap_reference_data  # noqa: E402

EXIT_OK = 0
EXIT_REFUSED = 2
EXIT_CONFLICT = 3


def _schema_head() -> str:
    return ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini"))).get_current_head()


def _database_revision(session) -> str | None:
    bind = session.get_bind()
    if "alembic_version" not in inspect(bind).get_table_names():
        return None
    return session.execute(text("SELECT version_num FROM alembic_version")).scalar()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="Report what would be created; write nothing.")
    parser.add_argument("--json", action="store_true", help="Print the report as JSON.")
    args = parser.parse_args(argv)

    settings = get_settings()
    errors = validate_runtime_settings(settings)
    if errors:
        print("Refusing to bootstrap reference data while configuration is invalid:")
        for error in errors:
            print(f"  - {error}")
        return EXIT_REFUSED

    session = get_session_factory()()
    try:
        head = _schema_head()
        current = _database_revision(session)
        if current != head:
            print(f"Refusing: the database is at {current or 'no revision'}, expected {head}.")
            print("Run the migrations first.")
            return EXIT_REFUSED
        try:
            report = bootstrap_reference_data(session, dry_run=args.check)
        except ReferenceBootstrapConflict as conflict:
            session.rollback()
            print("Existing configuration differs from the approved reference; nothing was written:")
            for item in conflict.conflicts:
                print(f"  - {item}")
            print("Review these rows with the configuration owner. The bootstrap never overwrites them.")
            return EXIT_CONFLICT
        if not args.check:
            session.commit()
        if args.json:
            print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
        else:
            verb = "Would create" if args.check else "Created"
            created = ", ".join(f"{kind}={count}" for kind, count in sorted(report.created.items())) or "nothing"
            print(f"{verb}: {created}.")
            unchanged = ", ".join(f"{kind}={count}" for kind, count in sorted(report.unchanged.items())) or "none"
            print(f"Already present: {unchanged}.")
        return EXIT_OK
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())

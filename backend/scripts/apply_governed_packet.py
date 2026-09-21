"""Apply a separately reviewed hierarchy or aggregate-source approval packet.

Discovery output is never applied directly. The packet must use an approval schema, every row
must say ``review_status: approved``, the command approval reference must match the packet, and
two distinct active users with ``manage_mappings`` permission must be named. The transaction is
all-or-nothing and emits an audit record. No DHIS2 endpoint is contacted by this command.

Examples (from backend/):
    python scripts/apply_governed_packet.py hierarchy reviewed-hierarchy.json \
        --actor admin.one --reviewer admin.two --approval-reference MOH-HIERARCHY-2026-01
    python scripts/apply_governed_packet.py source-mapping reviewed-sources.json \
        --actor admin.one --reviewer clinical.reviewer \
        --approval-reference MOH-SOURCES-2026-01 --mapping-version ug-hmis-2026-v1
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
from sqlalchemy import inspect, select, text  # noqa: E402

from app.db.session import get_session_factory  # noqa: E402
from app.models import User  # noqa: E402
from app.services.governed_imports import (  # noqa: E402
    GovernedImportError,
    apply_hierarchy_packet,
    apply_source_mapping_packet,
)

EXIT_OK = 0
EXIT_REFUSED = 2


def _schema_head() -> str:
    return ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini"))).get_current_head()


def _database_revision(session) -> str | None:
    bind = session.get_bind()
    if "alembic_version" not in inspect(bind).get_table_names():
        return None
    return session.execute(text("SELECT version_num FROM alembic_version")).scalar()


def _active_user(session, username: str) -> User:
    user = session.scalar(
        select(User).where(User.username == username, User.is_active.is_(True))
    )
    if user is None:
        raise GovernedImportError(
            "active_user_not_found", f"Active user {username!r} was not found."
        )
    return user


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("kind", choices=("hierarchy", "source-mapping"))
    parser.add_argument("packet", type=Path)
    parser.add_argument("--actor", required=True, help="User applying the reviewed decision.")
    parser.add_argument("--reviewer", required=True, help="Different user who approved it.")
    parser.add_argument("--approval-reference", required=True)
    parser.add_argument("--mapping-version", help="Required for a source-mapping packet.")
    parser.add_argument(
        "--check", action="store_true", help="Validate the complete transaction, then roll it back."
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        packet = json.loads(args.packet.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Refusing to apply unreadable packet: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    if not isinstance(packet, dict):
        print("Refusing to apply: the packet root must be a JSON object.", file=sys.stderr)
        return EXIT_REFUSED
    if args.kind == "source-mapping" and not args.mapping_version:
        print("Refusing to apply: --mapping-version is required.", file=sys.stderr)
        return EXIT_REFUSED

    session = get_session_factory()()
    try:
        head = _schema_head()
        current = _database_revision(session)
        if current != head:
            print(
                f"Refusing: the database is at {current or 'no revision'}, expected {head}.",
                file=sys.stderr,
            )
            return EXIT_REFUSED
        actor = _active_user(session, args.actor)
        reviewer = _active_user(session, args.reviewer)
        if args.kind == "hierarchy":
            result = apply_hierarchy_packet(
                session,
                packet=packet,
                actor=actor,
                reviewer=reviewer,
                approval_reference=args.approval_reference,
            )
        else:
            result = apply_source_mapping_packet(
                session,
                packet=packet,
                actor=actor,
                reviewer=reviewer,
                approval_reference=args.approval_reference,
                mapping_version=args.mapping_version,
            )
        if args.check:
            session.rollback()
        else:
            session.commit()
    except GovernedImportError as exc:
        session.rollback()
        print(f"Refused [{exc.code}]: {exc.message}", file=sys.stderr)
        return EXIT_REFUSED
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    report = result.as_dict()
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        verb = "Validated" if args.check else "Applied"
        print(
            f"{verb} approved packet {report['packet_sha256']}: "
            f"created={report['created']}, unchanged={report['unchanged']}."
        )
        if report["coverage"] is not None:
            for programme, coverage in report["coverage"].items():
                print(
                    f"{programme}: {coverage['resolved_count']}/{coverage['required_count']} "
                    f"source keys covered; complete={coverage['complete']}."
                )
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())

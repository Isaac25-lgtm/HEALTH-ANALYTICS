"""Create the first system administrator for a fresh deployment.

There is no default username and no default password. The password is read from a secure
prompt or from HPIP_ADMIN_PASSWORD, is never printed, never logged and never stored in
plaintext. The command is idempotent: if a system administrator already exists it changes
nothing.

It refuses to run when the deployment's own configuration validation reports blocking errors,
so an insecure production instance cannot be given an administrator.

Usage (inside the API container or with the production environment loaded):
    python scripts/create_initial_admin.py --username <name> --display-name "<full name>"
    HPIP_ADMIN_PASSWORD=... python scripts/create_initial_admin.py --username <name> --no-prompt
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from app.config import get_settings, validate_runtime_settings  # noqa: E402
from app.db.session import get_session_factory  # noqa: E402
from app.domain.enums import ProgrammeCode  # noqa: E402
from app.models import (  # noqa: E402
    OrgUnit,
    Programme,
    Role,
    User,
    UserGeographyScope,
    UserProgrammeScope,
    UserRole,
)
from app.services.audit import write_audit  # noqa: E402
from app.services.passwords import hash_password  # noqa: E402

MIN_PASSWORD_LENGTH = 14
WEAK_MARKERS = ("password", "change-me", "changeme", "admin123", "dev-only", "hpip123", "letmein")


def _password(prompt: bool) -> str:
    supplied = os.environ.get("HPIP_ADMIN_PASSWORD")
    if supplied:
        return supplied
    if not prompt:
        raise SystemExit("No password supplied. Set HPIP_ADMIN_PASSWORD or drop --no-prompt.")
    first = getpass.getpass("New administrator password: ")
    second = getpass.getpass("Repeat password: ")
    if first != second:
        raise SystemExit("The passwords did not match. Nothing was created.")
    return first


def _check_password(value: str) -> None:
    if len(value) < MIN_PASSWORD_LENGTH:
        raise SystemExit(f"The password must be at least {MIN_PASSWORD_LENGTH} characters. Nothing was created.")
    lowered = value.lower()
    if any(marker in lowered for marker in WEAK_MARKERS):
        raise SystemExit("The password looks like a placeholder. Nothing was created.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--username", required=True, help="Account name for the first administrator.")
    parser.add_argument("--display-name", help="Full name shown in the interface.")
    parser.add_argument("--email")
    parser.add_argument("--org-unit-code", help="Geography scope (defaults to the root organisation unit).")
    parser.add_argument("--no-prompt", action="store_true", help="Require HPIP_ADMIN_PASSWORD instead of prompting.")
    args = parser.parse_args(argv)

    settings = get_settings()
    errors = validate_runtime_settings(settings)
    if errors:
        print("Refusing to create an administrator while configuration is invalid:")
        for error in errors:
            print(f"  - {error}")
        return 2
    if settings.seed_dev_data and settings.is_production:
        print("Refusing to run: SEED_DEV_DATA is true in a production environment.")
        return 2

    session = get_session_factory()()
    try:
        existing = session.scalar(select(User).where(User.is_system_admin.is_(True), User.is_active.is_(True)))
        if existing is not None:
            print("A system administrator already exists; nothing was created.")
            return 0
        if session.scalar(select(User).where(User.username == args.username)) is not None:
            print("That username is already taken; nothing was created.")
            return 2
        password = _password(prompt=not args.no_prompt)
        _check_password(password)
        role = session.scalar(select(Role).where(Role.code == "system_administrator"))
        if role is None:
            print("The system_administrator role is missing. Run the migrations and reference seed first.")
            return 2
        org_unit = (
            session.scalar(select(OrgUnit).where(OrgUnit.code == args.org_unit_code))
            if args.org_unit_code
            else session.scalar(select(OrgUnit).where(OrgUnit.parent_id.is_(None)).order_by(OrgUnit.code))
        )
        if org_unit is None:
            print("No organisation unit is available for the geography scope; nothing was created.")
            return 2
        user = User(
            username=args.username,
            display_name=args.display_name or args.username,
            email=args.email,
            password_hash=hash_password(password),
            is_active=True,
            is_system_admin=True,
            identity_provider="local",
        )
        session.add(user)
        session.flush()
        session.add(UserRole(user_id=user.id, role_id=role.id))
        session.add(UserGeographyScope(user_id=user.id, org_unit_id=org_unit.id))
        for programme in session.scalars(select(Programme).where(Programme.code != ProgrammeCode.MPDSR.value)).all():
            session.add(UserProgrammeScope(user_id=user.id, programme_id=programme.id))
        write_audit(
            session,
            actor_user_id=user.id,
            action="initial_admin_created",
            resource_type="user",
            resource_id=str(user.id),
            after={
                "username": user.username,
                "org_unit_code": org_unit.code,
                "identity_provider": user.identity_provider,
                "mpdsr_programme_granted": False,
            },
            reason="Initial administrator provisioning (scripts/create_initial_admin.py).",
        )
        session.commit()
        # The password is never echoed back.
        print(f"Created system administrator '{user.username}' scoped to {org_unit.code}.")
        print("MPDSR programme access was not granted; grant it explicitly if the role requires it.")
        return 0
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())

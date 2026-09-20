"""Provision an HPIP user whose password is verified by the live DHIS2 server.

This command creates only the local authorisation record. It never asks for, receives or
stores the staff member's DHIS2 password. On the user's first successful sign-in HPIP calls
DHIS2 ``/api/me`` and binds the immutable DHIS2 subject to this pre-provisioned account.

Roles, geography scopes and programme scopes must already exist and must be named explicitly.
The system-administrator role is deliberately excluded; use ``create_initial_admin.py`` for
the one bootstrap administrator. MPDSR access requires an additional explicit acknowledgement.
"""

from __future__ import annotations

import argparse
import secrets
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


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--username", required=True, help="The user's exact DHIS2 username.")
    parser.add_argument("--display-name", required=True, help="Name shown in HPIP.")
    parser.add_argument("--email")
    parser.add_argument("--role", action="append", required=True, help="Existing non-admin role code; repeatable.")
    parser.add_argument(
        "--org-unit-code",
        action="append",
        required=True,
        help="Existing active HPIP organisation-unit code; repeatable.",
    )
    parser.add_argument(
        "--programme",
        action="append",
        required=True,
        choices=tuple(programme.value for programme in ProgrammeCode),
        help="Programme scope; repeatable.",
    )
    parser.add_argument(
        "--allow-sensitive-mpdsr",
        action="store_true",
        help="Required acknowledgement when explicitly granting the sensitive MPDSR programme.",
    )
    args = parser.parse_args(argv)

    username = args.username.strip()
    display_name = args.display_name.strip()
    role_codes = _unique(args.role)
    org_codes = _unique(args.org_unit_code)
    programme_codes = _unique(args.programme)
    if not 1 <= len(username) <= 80 or not display_name:
        print("Username must be 1-80 characters and display name must not be blank; nothing was created.")
        return 2
    if "system_administrator" in role_codes:
        print("Refusing system_administrator here; use create_initial_admin.py for bootstrap administration.")
        return 2
    if ProgrammeCode.MPDSR.value in programme_codes and not args.allow_sensitive_mpdsr:
        print("Refusing MPDSR access without --allow-sensitive-mpdsr; nothing was created.")
        return 2

    settings = get_settings()
    errors = validate_runtime_settings(settings)
    if errors:
        print("Refusing to provision a user while configuration is invalid:")
        for error in errors:
            print(f"  - {error}")
        return 2
    if not settings.dhis2_enabled or not settings.dhis2_login_enabled:
        print("Refusing: DHIS2_ENABLED and DHIS2_LOGIN_ENABLED must both be true.")
        return 2

    session = get_session_factory()()
    try:
        if session.scalar(select(User).where(User.username == username)) is not None:
            print("That username already exists; nothing was changed.")
            return 2

        roles = session.scalars(select(Role).where(Role.code.in_(role_codes), Role.is_active.is_(True))).all()
        roles_by_code = {row.code: row for row in roles}
        missing_roles = [code for code in role_codes if code not in roles_by_code]
        if missing_roles:
            print(f"Unknown or inactive role(s): {', '.join(missing_roles)}; nothing was created.")
            return 2

        org_units = session.scalars(
            select(OrgUnit).where(OrgUnit.code.in_(org_codes), OrgUnit.active.is_(True))
        ).all()
        orgs_by_code = {row.code: row for row in org_units}
        missing_orgs = [code for code in org_codes if code not in orgs_by_code]
        if missing_orgs:
            print(f"Unknown or inactive organisation unit(s): {', '.join(missing_orgs)}; nothing was created.")
            return 2

        programmes = session.scalars(
            select(Programme).where(Programme.code.in_(programme_codes), Programme.active.is_(True))
        ).all()
        programmes_by_code = {row.code: row for row in programmes}
        missing_programmes = [code for code in programme_codes if code not in programmes_by_code]
        if missing_programmes:
            print(f"Unknown or inactive programme(s): {', '.join(missing_programmes)}; nothing was created.")
            return 2

        # This value satisfies the legacy non-null column but the DHIS2 login branch never uses it.
        user = User(
            username=username,
            display_name=display_name,
            email=args.email.strip() if args.email else None,
            password_hash=hash_password(secrets.token_urlsafe(48)),
            is_active=True,
            is_system_admin=False,
            identity_provider="dhis2",
            external_subject=None,
        )
        session.add(user)
        session.flush()
        for code in role_codes:
            session.add(UserRole(user_id=user.id, role_id=roles_by_code[code].id))
        for code in org_codes:
            session.add(UserGeographyScope(user_id=user.id, org_unit_id=orgs_by_code[code].id))
        for code in programme_codes:
            session.add(UserProgrammeScope(user_id=user.id, programme_id=programmes_by_code[code].id))
        write_audit(
            session,
            actor_user_id=None,
            action="dhis2_user_provisioned",
            resource_type="user",
            resource_id=str(user.id),
            after={
                "username": username,
                "roles": role_codes,
                "org_unit_codes": org_codes,
                "programme_codes": programme_codes,
                "identity_provider": "dhis2",
            },
            reason="Operator-controlled provisioning (scripts/provision_dhis2_user.py).",
        )
        session.commit()
        print(f"Provisioned DHIS2 user '{username}'. The account will bind to DHIS2 on first sign-in.")
        return 0
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())

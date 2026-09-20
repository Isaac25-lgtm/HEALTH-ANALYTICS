"""Work package O: no development login behaviour, and a safe first administrator.

The login form ships blank, and the initial administrator is created only through an idempotent,
audited command that never echoes the password and refuses an insecure deployment.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.models import AuditLog, Programme, User, UserProgrammeScope
from app.services.passwords import verify_password
from scripts import create_initial_admin as provisioning

FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "src"


def _run(monkeypatch, session, argv, password: str | None = "a-strong-operator-chosen-secret"):
    """Run the provisioning command against the test session."""
    monkeypatch.setattr(provisioning, "get_session_factory", lambda: lambda: session)
    if password is None:
        monkeypatch.delenv("HPIP_ADMIN_PASSWORD", raising=False)
    else:
        monkeypatch.setenv("HPIP_ADMIN_PASSWORD", password)
    return provisioning.main(argv)


def test_login_form_ships_blank():
    page = (FRONTEND / "app" / "login" / "page.tsx").read_text(encoding="utf-8")
    assert 'useState("")' in page
    assert "national.analyst" not in page
    assert "dev-only" not in page
    # No password is ever prefilled in any environment.
    assert 'type="password"' in page
    assert "value={password}" in page


def test_no_synthetic_username_is_prefilled_anywhere_in_the_frontend():
    offenders = [
        str(path.relative_to(FRONTEND))
        for path in FRONTEND.rglob("*.tsx")
        if "national.analyst" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_creates_one_administrator_and_is_idempotent(session, monkeypatch, capsys):
    # The seeded synthetic admin must not block a fresh deployment check, so remove it first.
    for existing in session.scalars(select(User).where(User.is_system_admin.is_(True))).all():
        existing.is_system_admin = False
    session.commit()

    code = _run(monkeypatch, session, ["--username", "moh.admin", "--display-name", "MoH Administrator"])
    assert code == 0
    user = session.scalar(select(User).where(User.username == "moh.admin"))
    assert user is not None and user.is_system_admin and user.is_active
    assert verify_password("a-strong-operator-chosen-secret", user.password_hash)
    assert user.password_hash != "a-strong-operator-chosen-secret"

    # MPDSR is never granted implicitly.
    mpdsr = session.scalar(select(Programme).where(Programme.code == "MPDSR"))
    granted = session.scalar(
        select(UserProgrammeScope).where(
            UserProgrammeScope.user_id == user.id, UserProgrammeScope.programme_id == mpdsr.id
        )
    )
    assert granted is None

    audit = session.scalar(select(AuditLog).where(AuditLog.action == "initial_admin_created"))
    assert audit is not None
    assert "a-strong-operator-chosen-secret" not in json.dumps(audit.after_json)

    output = capsys.readouterr().out
    assert "a-strong-operator-chosen-secret" not in output

    # Running it again changes nothing.
    again = _run(monkeypatch, session, ["--username", "second.admin"])
    assert again == 0
    assert session.scalar(select(User).where(User.username == "second.admin")) is None
    assert "already exists" in capsys.readouterr().out


@pytest.mark.parametrize("weak", ["short", "change-me-please-now", "hpip-password-2026"])
def test_weak_or_placeholder_passwords_are_refused(session, monkeypatch, weak):
    for existing in session.scalars(select(User).where(User.is_system_admin.is_(True))).all():
        existing.is_system_admin = False
    session.commit()
    with pytest.raises(SystemExit):
        _run(monkeypatch, session, ["--username", "weak.admin"], password=weak)
    assert session.scalar(select(User).where(User.username == "weak.admin")) is None


def test_refuses_to_run_on_an_invalid_production_deployment(session, monkeypatch, capsys):
    monkeypatch.setattr(get_settings(), "app_env", "production")
    monkeypatch.setattr(get_settings(), "rate_limit_backend", "memory")
    code = _run(monkeypatch, session, ["--username", "unsafe.admin"])
    assert code == 2
    assert "Refusing to create an administrator" in capsys.readouterr().out
    assert session.scalar(select(User).where(User.username == "unsafe.admin")) is None


def test_missing_password_without_a_prompt_is_refused(session, monkeypatch):
    for existing in session.scalars(select(User).where(User.is_system_admin.is_(True))).all():
        existing.is_system_admin = False
    session.commit()
    with pytest.raises(SystemExit, match="No password supplied"):
        _run(monkeypatch, session, ["--username", "no.password.admin", "--no-prompt"], password=None)


def test_creates_dhis2_administrator_without_storing_the_dhis2_password(session, monkeypatch):
    for existing in session.scalars(select(User).where(User.is_system_admin.is_(True))).all():
        existing.is_system_admin = False
    session.commit()
    monkeypatch.setattr(get_settings(), "dhis2_enabled", True)
    monkeypatch.setattr(get_settings(), "dhis2_login_enabled", True)
    monkeypatch.setattr(get_settings(), "dhis2_base_url", "https://hmis.health.go.ug")
    monkeypatch.setattr(get_settings(), "dhis2_username", "service.user")
    monkeypatch.setattr(get_settings(), "dhis2_password", "service-secret")
    supplied = "this-value-must-never-be-stored"

    code = _run(
        monkeypatch,
        session,
        ["--username", "real.dhis2.user", "--identity-provider", "dhis2", "--no-prompt"],
        password=supplied,
    )

    assert code == 0
    user = session.scalar(select(User).where(User.username == "real.dhis2.user"))
    assert user is not None
    assert user.identity_provider == "dhis2"
    assert user.external_subject is None
    assert not verify_password(supplied, user.password_hash)

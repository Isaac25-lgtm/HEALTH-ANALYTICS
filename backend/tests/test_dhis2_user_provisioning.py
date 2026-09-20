from sqlalchemy import select

from app.config import get_settings
from app.models import AuditLog, User, UserGeographyScope, UserProgrammeScope, UserRole
from scripts import provision_dhis2_user as provisioning


def _enable(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "dhis2_enabled", True)
    monkeypatch.setattr(settings, "dhis2_login_enabled", True)
    monkeypatch.setattr(settings, "dhis2_base_url", "https://hmis.health.go.ug")
    monkeypatch.setattr(settings, "dhis2_username", "service.user")
    monkeypatch.setattr(settings, "dhis2_password", "service-secret")


def _run(monkeypatch, session, argv: list[str]) -> int:
    _enable(monkeypatch)
    monkeypatch.setattr(provisioning, "get_session_factory", lambda: lambda: session)
    return provisioning.main(argv)


def test_provisions_scoped_dhis2_user_without_a_password(session, monkeypatch, capsys):
    code = _run(
        monkeypatch,
        session,
        [
            "--username", "district.user",
            "--display-name", "District User",
            "--role", "district_mch_focal",
            "--org-unit-code", "UG",
            "--programme", "MNCH",
            "--programme", "EPI",
        ],
    )

    assert code == 0
    user = session.scalar(select(User).where(User.username == "district.user"))
    assert user is not None
    assert user.identity_provider == "dhis2"
    assert user.external_subject is None
    assert not user.is_system_admin
    assert session.query(UserRole).filter_by(user_id=user.id).count() == 1
    assert session.query(UserGeographyScope).filter_by(user_id=user.id).count() == 1
    assert session.query(UserProgrammeScope).filter_by(user_id=user.id).count() == 2
    audit = session.scalar(select(AuditLog).where(AuditLog.action == "dhis2_user_provisioned"))
    assert audit is not None and audit.after_json["programme_codes"] == ["MNCH", "EPI"]
    assert "password" not in str(audit.after_json).lower()
    assert "bind to DHIS2" in capsys.readouterr().out


def test_refuses_duplicate_without_changing_scopes(session, monkeypatch, capsys):
    argv = [
        "--username", "duplicate.user",
        "--display-name", "Duplicate User",
        "--role", "view_only",
        "--org-unit-code", "UG",
        "--programme", "MNCH",
    ]
    assert _run(monkeypatch, session, argv) == 0
    user = session.scalar(select(User).where(User.username == "duplicate.user"))
    assert _run(monkeypatch, session, argv[:-1] + ["EPI"]) == 2
    assert session.query(UserProgrammeScope).filter_by(user_id=user.id).count() == 1
    assert "nothing was changed" in capsys.readouterr().out


def test_sensitive_and_admin_grants_require_separate_paths(session, monkeypatch, capsys):
    base = [
        "--username", "sensitive.user",
        "--display-name", "Sensitive User",
        "--role", "mpdsr_analyst",
        "--org-unit-code", "UG",
        "--programme", "MPDSR",
    ]
    assert _run(monkeypatch, session, base) == 2
    assert session.scalar(select(User).where(User.username == "sensitive.user")) is None
    assert "--allow-sensitive-mpdsr" in capsys.readouterr().out

    admin = base.copy()
    admin[admin.index("mpdsr_analyst")] = "system_administrator"
    admin[admin.index("MPDSR")] = "MNCH"
    assert _run(monkeypatch, session, admin) == 2
    assert "create_initial_admin.py" in capsys.readouterr().out


def test_explicit_mpdsr_acknowledgement_provisions_user(session, monkeypatch):
    assert _run(
        monkeypatch,
        session,
        [
            "--username", "mpdsr.user",
            "--display-name", "MPDSR User",
            "--role", "mpdsr_analyst",
            "--org-unit-code", "UG",
            "--programme", "MPDSR",
            "--allow-sensitive-mpdsr",
        ],
    ) == 0
    assert session.scalar(select(User).where(User.username == "mpdsr.user")) is not None

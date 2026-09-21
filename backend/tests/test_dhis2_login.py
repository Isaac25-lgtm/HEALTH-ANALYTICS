from __future__ import annotations

import pytest
from sqlalchemy import select

from app.api.routes import auth
from app.config import get_settings
from app.integrations.dhis2.errors import Dhis2AuthError, Dhis2TransientError
from app.models import AuthSession, User


class _ProfileClient:
    profile: dict = {"id": "LIVE_SUBJECT_1", "username": "national.analyst", "displayName": "Analyst"}
    error: Exception | None = None
    received_auth: tuple[str, str] | None = None

    def __init__(self, settings, *, basic_auth=None, **kwargs):
        del settings, kwargs
        type(self).received_auth = basic_auth

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def get_json(self, path, params=None):
        assert path == "/api/me"
        assert params == {"fields": "id,username,displayName"}
        if type(self).error:
            raise type(self).error
        return dict(type(self).profile)


def _enable(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "dhis2_enabled", True)
    monkeypatch.setattr(settings, "dhis2_login_enabled", True)
    monkeypatch.setattr(settings, "dhis2_base_url", "https://hmis.health.go.ug")
    monkeypatch.setattr(auth, "Dhis2HttpClient", _ProfileClient)
    _ProfileClient.error = None
    _ProfileClient.profile = {
        "id": "LIVE_SUBJECT_1",
        "username": "national.analyst",
        "displayName": "Analyst",
    }
    _ProfileClient.received_auth = None


def test_preprovisioned_dhis2_user_authenticates_and_binds_subject(client, session, monkeypatch):
    _enable(monkeypatch)
    user = session.scalar(select(User).where(User.username == "national.analyst"))
    user.identity_provider = "dhis2"
    user.external_subject = None
    original_hash = user.password_hash
    session.commit()

    response = client.post(
        "/auth/login",
        json={"username": "national.analyst", "password": "remote-secret-value"},
    )

    assert response.status_code == 200
    assert "hpip_session" in response.cookies
    assert _ProfileClient.received_auth == ("national.analyst", "remote-secret-value")
    session.refresh(user)
    assert user.external_subject == "LIVE_SUBJECT_1"
    assert user.password_hash == original_hash


def test_dhis2_subject_or_username_mismatch_is_rejected(client, session, monkeypatch):
    _enable(monkeypatch)
    user = session.scalar(select(User).where(User.username == "national.analyst"))
    user.identity_provider = "dhis2"
    user.external_subject = "EXPECTED_SUBJECT"
    session.commit()
    _ProfileClient.profile = {"id": "OTHER_SUBJECT", "username": "national.analyst"}

    response = client.post(
        "/auth/login",
        json={"username": "national.analyst", "password": "remote-secret-value"},
    )

    assert response.status_code == 401
    assert session.scalar(select(AuthSession).where(AuthSession.user_id == user.id)) is None


def test_dhis2_outage_returns_service_unavailable_not_bad_password(client, session, monkeypatch):
    _enable(monkeypatch)
    user = session.scalar(select(User).where(User.username == "national.analyst"))
    user.identity_provider = "dhis2"
    session.commit()
    _ProfileClient.profile = {"id": "LIVE_SUBJECT_1", "username": "national.analyst"}
    _ProfileClient.error = Dhis2TransientError()

    response = client.post(
        "/auth/login",
        json={"username": "national.analyst", "password": "remote-secret-value"},
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "dhis2_login_unavailable"


def test_upstream_401_while_dhis2_is_unhealthy_is_not_reported_as_a_wrong_password(monkeypatch):
    """The national instance returns spurious 401s under load.

    Telling someone their password is wrong when the upstream is merely unwell invites them to
    change a working credential, so a rejection is only believed when /api/ping confirms the
    instance is healthy.
    """
    from fastapi import HTTPException

    from app.api.routes import auth as auth_routes

    settings = get_settings().model_copy(
        update={
            "dhis2_enabled": True,
            "dhis2_login_enabled": True,
            "dhis2_base_url": "https://example.test",
            "dhis2_username": "tester",
            "dhis2_password": "secret-password",
        }
    )

    class _Body:
        username = "someone"
        password = "whatever"

    class _User:
        username = "someone"
        external_subject = None

    def _raise_auth(*args, **kwargs):
        raise Dhis2AuthError()

    monkeypatch.setattr(auth_routes.Dhis2HttpClient, "get_json", _raise_auth)

    # Instance unhealthy -> temporary upstream error, never "invalid credentials".
    monkeypatch.setattr(auth_routes, "_dhis2_reachable", lambda _s: False)
    with pytest.raises(HTTPException) as excinfo:
        auth_routes._authenticate_dhis2(_Body(), _User(), settings)
    assert excinfo.value.status_code == 503
    assert excinfo.value.detail["code"] == "dhis2_login_unavailable"

    # Instance healthy -> the rejection is believed and sign-in fails normally.
    monkeypatch.setattr(auth_routes, "_dhis2_reachable", lambda _s: True)
    assert auth_routes._authenticate_dhis2(_Body(), _User(), settings) == {}

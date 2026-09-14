from sqlalchemy import select

from app.models import AuditLog


def test_login_creates_audit_event(client, session):
    response = client.post(
        "/auth/login", json={"username": "national.analyst", "password": "dev-only-change-me"}
    )
    assert response.status_code == 200
    entry = session.scalar(select(AuditLog).where(AuditLog.action == "login"))
    assert entry is not None
    assert entry.resource_type == "session"

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import AuthSession, LoginAttempt


def create_session(session: Session, user_id: UUID, settings: Settings, ip: str | None) -> AuthSession:
    now = datetime.now(UTC)
    row = AuthSession(
        user_id=user_id,
        jti=uuid4().hex,
        csrf_token=uuid4().hex,
        expires_at=now + timedelta(minutes=settings.auth_token_ttl_minutes),
        ip_address=ip,
    )
    session.add(row)
    session.flush()
    return row


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def active_session(session: Session, jti: str) -> AuthSession | None:
    row = session.scalar(select(AuthSession).where(AuthSession.jti == jti))
    if row is None or row.revoked_at is not None:
        return None
    if _aware(row.expires_at) <= datetime.now(UTC):
        return None
    return row


def revoke_session(session: Session, jti: str | None) -> None:
    if not jti:
        return
    row = session.scalar(select(AuthSession).where(AuthSession.jti == jti))
    if row is not None and row.revoked_at is None:
        row.revoked_at = datetime.now(UTC)


def record_login_attempt(session: Session, username: str, succeeded: bool, ip: str | None) -> None:
    session.add(LoginAttempt(username=username[:80], succeeded=succeeded, ip_address=ip))


def login_attempts_exceeded(session: Session, username: str, settings: Settings) -> bool:
    since = datetime.now(UTC) - timedelta(seconds=settings.login_window_seconds)
    rows = session.scalars(
        select(LoginAttempt).where(
            LoginAttempt.username == username,
            LoginAttempt.succeeded.is_(False),
        )
    ).all()
    recent = [row for row in rows if _aware(row.created_at) >= since]
    return len(recent) >= settings.login_max_attempts

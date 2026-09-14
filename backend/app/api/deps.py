from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.session import get_db, mark_writable
from app.models import User
from app.services.authorization import AuthorizationError
from app.services.sessions import active_session
from app.services.tokens import TokenError, decode_access_token


def get_current_user(
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    token = request.cookies.get(settings.auth_cookie_name)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "unauthenticated", "message": "Authentication required."},
        )
    try:
        payload = decode_access_token(token, settings)
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_token", "message": "Access token is invalid or expired."},
        ) from exc
    row = active_session(session, str(payload["jti"]))
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "session_revoked", "message": "Session is not active."},
        )
    user = session.get(User, UUID(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "unauthenticated", "message": "User is not active."},
        )
    request.state.session_jti = row.jti
    return user


def require_write(session: Session = Depends(get_db)) -> Session:
    """Mark the request session as a write unit of work. Read routes stay read-only."""
    return mark_writable(session)


def raise_authz(error: AuthorizationError) -> None:
    status_code = status.HTTP_403_FORBIDDEN
    if error.code == "not_found":
        status_code = status.HTTP_404_NOT_FOUND
    if error.code == "unauthenticated":
        status_code = status.HTTP_401_UNAUTHORIZED
    if error.code in {"invalid_input", "snapshot_mismatch", "snapshot_required"}:
        status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    if error.code == "snapshot_conflict":
        status_code = status.HTTP_409_CONFLICT
    if error.code == "rate_limited":
        status_code = status.HTTP_429_TOO_MANY_REQUESTS
    if error.code in {"rate_limiter_unavailable", "export_queue_unavailable"}:
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    if error.code in {"export_retry_not_permitted"}:
        status_code = status.HTTP_409_CONFLICT
    raise HTTPException(
        status_code=status_code,
        detail={"code": error.code, "message": error.message},
    )


def parse_uuid(value: str, field: str = "id") -> UUID:
    try:
        return UUID(str(value))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_id", "message": f"{field} is not a valid identifier."},
        ) from exc

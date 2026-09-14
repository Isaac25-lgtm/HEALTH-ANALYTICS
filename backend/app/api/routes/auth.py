from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_write
from app.config import Settings, get_settings
from app.models import User
from app.schemas.api import LoginRequest, SessionLoginResponse
from app.services.audit import write_audit
from app.services.passwords import verify_password
from app.services.sessions import (
    create_session,
    login_attempts_exceeded,
    record_login_attempt,
    revoke_session,
)
from app.services.tokens import create_access_token, decode_access_token

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=SessionLoginResponse)
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    session: Session = Depends(require_write),
    settings: Settings = Depends(get_settings),
) -> SessionLoginResponse:
    if not 1 <= len(body.username) <= 80 or not 8 <= len(body.password) <= 128:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "invalid_credentials_format",
                "message": "Username or password length is invalid.",
            },
        )
    ip = request.client.host if request.client else None
    if login_attempts_exceeded(session, body.username, settings):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"code": "login_throttled", "message": "Too many failed sign-in attempts."},
        )
    user = session.scalar(select(User).where(User.username == body.username))
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        record_login_attempt(session, body.username, False, ip)
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_credentials", "message": "Username or password is incorrect."},
        )
    auth_session = create_session(session, user.id, settings, ip)
    token = create_access_token(
        user.id,
        settings,
        jti=auth_session.jti,
        csrf_token=auth_session.csrf_token,
    )
    secure = settings.auth_cookie_secure or settings.is_production
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        httponly=True,
        secure=secure,
        samesite=settings.auth_cookie_samesite,
        max_age=settings.auth_token_ttl_minutes * 60,
        path="/",
    )
    response.set_cookie(
        key=settings.auth_csrf_cookie_name,
        value=auth_session.csrf_token,
        httponly=False,
        secure=secure,
        samesite=settings.auth_cookie_samesite,
        max_age=settings.auth_token_ttl_minutes * 60,
        path="/",
    )
    record_login_attempt(session, body.username, True, ip)
    write_audit(
        session,
        actor_user_id=user.id,
        action="login",
        resource_type="session",
        resource_id=str(user.id),
        ip_address=ip,
        commit=True,
    )
    return SessionLoginResponse(ok=True, csrf_token=auth_session.csrf_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    session: Session = Depends(require_write),
    settings: Settings = Depends(get_settings),
) -> None:
    token = request.cookies.get(settings.auth_cookie_name)
    jti = None
    if token:
        try:
            jti = decode_access_token(token, settings)["jti"]
        except Exception:  # noqa: BLE001
            jti = None
    revoke_session(session, jti)
    response.delete_cookie(settings.auth_cookie_name, path="/")
    response.delete_cookie(settings.auth_csrf_cookie_name, path="/")
    write_audit(
        session,
        actor_user_id=None,
        action="logout",
        resource_type="session",
        ip_address=request.client.host if request.client else None,
        commit=True,
    )

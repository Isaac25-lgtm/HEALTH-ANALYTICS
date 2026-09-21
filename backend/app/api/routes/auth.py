from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_write
from app.config import Settings, get_settings
from app.integrations.dhis2.errors import Dhis2AuthError, Dhis2Error
from app.integrations.dhis2.http import Dhis2HttpClient
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


def _invalid_credentials(session: Session, username: str, ip: str | None) -> None:
    record_login_attempt(session, username, False, ip)
    session.commit()
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "invalid_credentials", "message": "Username or password is incorrect."},
    )


def _dhis2_reachable(settings: Settings) -> bool:
    """Whether DHIS2 is answering at all, checked without credentials.

    ``/api/ping`` needs no authentication, so this adds no failed sign-in attempt and cannot
    contribute to an account lockout. A single bounded request is made; any error is treated as
    "not reachable" so the caller fails towards the temporary-upstream answer.
    """
    import httpx

    url = f"{settings.dhis2_base_url.rstrip('/')}/api/ping"
    try:
        with httpx.Client(timeout=min(settings.dhis2_timeout_seconds, 10), follow_redirects=False) as client:
            return client.get(url).status_code == 200
    except Exception:  # noqa: BLE001 - any failure means we cannot confirm the instance is healthy
        return False


def _dhis2_upstream_unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": "dhis2_login_unavailable",
            "message": "DHIS2 could not be reached to verify this sign-in. Please try again.",
        },
    )


def _authenticate_dhis2(body: LoginRequest, user: User, settings: Settings) -> dict:
    if not settings.dhis2_enabled or not settings.dhis2_login_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "dhis2_login_unavailable", "message": "DHIS2 sign-in is not available."},
        )
    path = f"{settings.dhis2_api_path_prefix.rstrip('/')}/me"
    try:
        with Dhis2HttpClient(settings, basic_auth=(body.username, body.password)) as client:
            profile = client.get_json(path, params={"fields": "id,username,displayName"})
    except Dhis2AuthError as exc:
        # A 401 means "wrong password" only if the instance is actually healthy. Under load this
        # host returns spurious 401s, and telling a user their password is wrong when it is not
        # invites them to change a working credential.
        if not _dhis2_reachable(settings):
            raise _dhis2_upstream_unavailable() from exc
        return {}
    except Dhis2Error as exc:
        raise _dhis2_upstream_unavailable() from exc
    returned_username = str(profile.get("username") or "")
    returned_subject = str(profile.get("id") or "")
    if returned_username.casefold() != user.username.casefold() or not returned_subject:
        return {}
    if user.external_subject and user.external_subject != returned_subject:
        return {}
    return profile


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
    if user is None or not user.is_active:
        _invalid_credentials(session, body.username, ip)
    if user.identity_provider == "dhis2":
        profile = _authenticate_dhis2(body, user, settings)
        if not profile:
            _invalid_credentials(session, body.username, ip)
        # Bind the immutable DHIS2 subject on first successful login. Passwords and tokens are
        # never written to the database or audit log.
        if user.external_subject is None:
            user.external_subject = str(profile["id"])
    elif not verify_password(body.password, user.password_hash):
        _invalid_credentials(session, body.username, ip)
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

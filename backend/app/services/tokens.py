from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
from jwt import InvalidTokenError

from app.config import Settings


class TokenError(ValueError):
    pass


def create_access_token(
    user_id: UUID,
    settings: Settings,
    *,
    jti: str | None = None,
    csrf_token: str,
) -> str:
    now = datetime.now(UTC)
    expire = now + timedelta(minutes=settings.auth_token_ttl_minutes)
    payload = {
        "sub": str(user_id),
        "exp": expire,
        "iat": now,
        "nbf": now,
        "typ": "access",
        "iss": settings.auth_issuer,
        "aud": settings.auth_audience,
        "jti": jti or uuid4().hex,
        "csrf": csrf_token,
    }
    return jwt.encode(payload, settings.auth_secret, algorithm="HS256")


def decode_access_token(token: str, settings: Settings) -> dict:
    try:
        payload = jwt.decode(
            token,
            settings.auth_secret,
            algorithms=["HS256"],
            issuer=settings.auth_issuer,
            audience=settings.auth_audience,
            options={"require": ["exp", "iat", "sub", "typ", "iss", "aud", "jti", "csrf"]},
        )
    except InvalidTokenError as exc:
        raise TokenError("Access token is invalid or expired.") from exc
    if payload.get("typ") != "access":
        raise TokenError("Token type is not an access token.")
    return payload

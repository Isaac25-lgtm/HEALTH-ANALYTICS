import secrets

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import get_settings
from app.services.tokens import TokenError, decode_access_token

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
SKIP_PATHS = {"/auth/login", "/health", "/ready", "/docs", "/openapi.json", "/redoc", "/"}


class CsrfMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        settings = get_settings()
        if request.method in SAFE_METHODS or request.url.path in SKIP_PATHS:
            return await call_next(request)
        cookie = request.cookies.get(settings.auth_csrf_cookie_name)
        header = request.headers.get(settings.auth_csrf_header_name)
        session_token = request.cookies.get(settings.auth_cookie_name)
        bound_csrf = None
        if session_token:
            try:
                bound_csrf = str(decode_access_token(session_token, settings).get("csrf") or "")
            except TokenError:
                bound_csrf = None
        valid = bool(
            cookie
            and header
            and bound_csrf
            and secrets.compare_digest(cookie, header)
            and secrets.compare_digest(cookie, bound_csrf)
        )
        if not valid:
            return JSONResponse(
                status_code=403,
                content={"code": "csrf_failed", "message": "CSRF validation failed."},
            )
        return await call_next(request)

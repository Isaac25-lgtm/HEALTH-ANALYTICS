from collections.abc import Callable

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.config import get_settings


def cors_origins() -> list[str]:
    return get_settings().cors_origins


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        settings = get_settings()
        host = request.headers.get("host", "").split(":")[0]
        if settings.is_production and settings.host_list and host not in settings.host_list:
            return JSONResponse(
                status_code=400,
                content={"code": "invalid_host", "message": "Host is not allowed."},
            )
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'"
        )
        if settings.hsts_enabled or (settings.is_production and settings.auth_cookie_secure):
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

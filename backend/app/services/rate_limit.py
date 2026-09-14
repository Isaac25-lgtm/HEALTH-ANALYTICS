"""Per-user action rate limits.

Staging and production use Redis so every API process shares one budget. The per-process
memory backend exists only for development and test, and only when RATE_LIMIT_BACKEND=memory
is set explicitly. A missing or unreachable Redis never degrades silently to per-process
limits: the request is refused with ``rate_limiter_unavailable`` (HTTP 503).
"""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import UTC, datetime
from uuid import UUID

from app.config import get_settings
from app.services.authorization import AuthorizationError

_hits: dict[tuple[str, str], deque[datetime]] = defaultdict(deque)

LIMITED = "rate_limited"
UNAVAILABLE = "rate_limiter_unavailable"


def check_rate(user_id: UUID, action: str, *, limit: int, window_seconds: int = 60) -> None:
    settings = get_settings()
    backend = settings.rate_limit_backend.strip().lower()
    if backend == "memory":
        if not settings.is_dev_or_test:
            raise AuthorizationError(UNAVAILABLE, "Per-process rate limiting is not permitted in this environment.")
        _memory_check(str(user_id), action, limit=limit, window_seconds=window_seconds)
        return
    if backend != "redis" or not settings.redis_url.strip():
        raise AuthorizationError(UNAVAILABLE, "Distributed rate limiter is not configured.")
    try:
        count = _redis_increment(str(user_id), action, window_seconds=window_seconds)
    except Exception:  # noqa: BLE001 - any client or network failure fails closed
        raise AuthorizationError(UNAVAILABLE, "Distributed rate limiter is unavailable.") from None
    if count > limit:
        raise AuthorizationError(LIMITED, "Too many requests for this action.")


def _memory_check(user_id: str, action: str, *, limit: int, window_seconds: int) -> None:
    now = datetime.now(UTC)
    bucket = _hits[(user_id, action)]
    cutoff = now.timestamp() - window_seconds
    while bucket and bucket[0].timestamp() < cutoff:
        bucket.popleft()
    if len(bucket) >= limit:
        raise AuthorizationError(LIMITED, "Too many requests for this action.")
    bucket.append(now)


def _redis_client():
    import redis

    return redis.Redis.from_url(
        get_settings().redis_url,
        socket_timeout=0.5,
        socket_connect_timeout=0.5,
    )


def _redis_increment(user_id: str, action: str, *, window_seconds: int) -> int:
    """Fixed-window counter. The window index is part of the key, so a busy client's
    counter still expires at the end of its window."""
    window = int(datetime.now(UTC).timestamp() // window_seconds)
    key = f"hpip:rate:{action}:{user_id}:{window}"
    pipe = _redis_client().pipeline()
    pipe.incr(key)
    pipe.expire(key, window_seconds + 1)
    count, _ttl = pipe.execute()
    return int(count)


def reset_rate_limits() -> None:
    _hits.clear()

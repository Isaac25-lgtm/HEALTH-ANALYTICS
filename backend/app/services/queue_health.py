"""Connectivity checks for Redis, the Celery broker and workers. Never returns URLs or secrets."""

from __future__ import annotations

from app.config import Settings


def redis_status(url: str) -> str:
    if not url.strip():
        return "unconfigured"
    try:
        import redis

        redis.Redis.from_url(url, socket_connect_timeout=0.5, socket_timeout=0.5).ping()
        return "ok"
    except Exception:  # noqa: BLE001
        return "unavailable"


def broker_status(settings: Settings) -> str:
    url = settings.celery_broker_url.strip()
    if not url:
        return "unconfigured"
    if url.startswith("memory://"):
        return "in_memory"
    if url.startswith(("redis://", "rediss://")):
        return redis_status(url)
    try:
        from kombu import Connection

        with Connection(url, connect_timeout=1) as connection:
            connection.ensure_connection(max_retries=1)
        return "ok"
    except Exception:  # noqa: BLE001
        return "unavailable"


def worker_status(timeout: float = 1.0) -> dict:
    """Ping workers through the broker. Only for authenticated operations views."""
    try:
        from app.workers.celery_app import celery_app
    except Exception:  # noqa: BLE001
        return {"status": "unavailable", "responding_workers": 0}
    if celery_app is None:
        return {"status": "not_installed", "responding_workers": 0}
    try:
        replies = celery_app.control.inspect(timeout=timeout).ping() or {}
    except Exception:  # noqa: BLE001
        return {"status": "unavailable", "responding_workers": 0}
    return {"status": "ok" if replies else "no_workers", "responding_workers": len(replies)}

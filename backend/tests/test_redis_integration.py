"""Real Redis: shared rate limiting and Celery dispatch/consumption over a Redis broker.

Runs when HPIP_REDIS_TEST_URL names a disposable Redis database (the CI service). It skips
locally when no Redis is configured; CI fails on skips (HPIP_FAIL_ON_SKIP=1).
"""

from __future__ import annotations

import os
import secrets
from uuid import uuid4

import pytest

from app.config import get_settings
from app.services.authorization import AuthorizationError
from app.services.queue_health import broker_status, redis_status
from app.services.rate_limit import check_rate
from app.workers.celery_app import PROBE_TASK_NAME, celery_config

REDIS_URL = os.environ.get("HPIP_REDIS_TEST_URL", "")
requires_redis = pytest.mark.skipif(
    not REDIS_URL,
    reason="Redis is not available (set HPIP_REDIS_TEST_URL to a disposable Redis database)",
)


@requires_redis
def test_real_redis_rate_limit_is_shared_and_fail_closed(monkeypatch):
    monkeypatch.setattr(get_settings(), "rate_limit_backend", "redis")
    monkeypatch.setattr(get_settings(), "redis_url", REDIS_URL)
    assert redis_status(REDIS_URL) == "ok"
    user = uuid4()
    action = f"ci:{secrets.token_hex(4)}"
    for _ in range(3):
        check_rate(user, action, limit=3, window_seconds=30)
    with pytest.raises(AuthorizationError) as limited:
        check_rate(user, action, limit=3, window_seconds=30)
    assert limited.value.code == "rate_limited"
    monkeypatch.setattr(get_settings(), "redis_url", "redis://127.0.0.1:1/0")
    with pytest.raises(AuthorizationError) as unavailable:
        check_rate(user, action, limit=3, window_seconds=30)
    assert unavailable.value.code == "rate_limiter_unavailable"


@requires_redis
def test_celery_dispatch_and_consumption_over_real_redis(monkeypatch):
    from celery import Celery
    from celery.contrib.testing.worker import start_worker

    app = Celery("hpip-redis-ci")
    config = celery_config()
    config.update({"broker_url": REDIS_URL, "result_backend": REDIS_URL})
    app.conf.update(config)

    @app.task(name=PROBE_TASK_NAME)
    def probe(nonce: str) -> str:
        return nonce

    monkeypatch.setattr(get_settings(), "celery_broker_url", REDIS_URL)
    assert broker_status(get_settings()) == "ok"
    queue = f"exports-ci-{secrets.token_hex(4)}"
    nonce = secrets.token_hex(8)
    with start_worker(app, pool="solo", perform_ping_check=False, queues=[queue], shutdown_timeout=30):
        assert app.send_task(PROBE_TASK_NAME, args=[nonce], queue=queue).get(timeout=60) == nonce

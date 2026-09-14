"""Verify queue dispatch and consumption end to end.

Publishes the harmless ``queue_health_probe`` task to the export queue and waits for a worker
to return the same nonce through the result backend. Exit code 0 means the broker, a worker
listening on the export queue and the result backend all work. Prints no URLs or secrets.

Usage (inside the API or worker container):
    python scripts/queue_smoke.py [--timeout 60]
"""

from __future__ import annotations

import argparse
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.workers.celery_app import PROBE_TASK_NAME, celery_app  # noqa: E402


def run(timeout: float) -> int:
    if celery_app is None:
        print("queue_smoke: Celery is not installed in this runtime.")
        return 2
    settings = get_settings()
    if not settings.celery_broker_url.strip():
        print("queue_smoke: CELERY_BROKER_URL is not configured.")
        return 2
    nonce = secrets.token_hex(8)
    try:
        result = celery_app.send_task(PROBE_TASK_NAME, args=[nonce], queue=settings.export_queue_name)
        echoed = result.get(timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        print(f"queue_smoke: failed ({type(exc).__name__}).")
        return 1
    if echoed != nonce:
        print("queue_smoke: worker returned an unexpected value.")
        return 1
    print(f"queue_smoke: ok (queue={settings.export_queue_name})")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=float, default=60.0)
    sys.exit(run(parser.parse_args().timeout))

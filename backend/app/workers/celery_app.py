"""Celery application for queued sync and export work.

Eager execution is never switched on here. Exports run in-request only when EXPORT_EAGER=true
is set explicitly in development/test, and sync jobs only when SYNC_EXECUTION=eager or
APP_ENV=test. Staging/production workers refuse to start with missing broker, result
backend, Redis or other blocking configuration.
"""

from __future__ import annotations

from app.config import get_settings, validate_runtime_settings

EXPORT_TASK_NAME = "app.workers.tasks.generate_export_job"
SYNC_TASK_NAME = "app.workers.tasks.execute_sync_job"
# Echoes a nonce. Used by scripts/queue_smoke.py to prove dispatch, consumption and results.
PROBE_TASK_NAME = "app.workers.tasks.queue_health_probe"


def celery_config() -> dict:
    settings = get_settings()
    return {
        "broker_url": settings.celery_broker_url or None,
        "result_backend": settings.celery_result_backend or None,
        "task_always_eager": False,
        "task_ignore_result": False,
        "task_acks_late": True,
        "task_reject_on_worker_lost": True,
        "worker_prefetch_multiplier": 1,
        "task_default_queue": "default",
        "task_routes": {
            EXPORT_TASK_NAME: {"queue": settings.export_queue_name},
            SYNC_TASK_NAME: {"queue": settings.sync_queue_name},
        },
        "task_publish_retry": True,
        "task_publish_retry_policy": {
            "max_retries": 2,
            "interval_start": 0,
            "interval_step": 0.5,
            "interval_max": 2,
        },
        "broker_connection_timeout": 3,
        "broker_connection_retry_on_startup": True,
        # Must exceed the export lease so a slow job is not redelivered while still running.
        "broker_transport_options": {"visibility_timeout": settings.export_job_lease_seconds * 2},
        "result_expires": 86_400,
        "worker_hijack_root_logger": False,
    }


def worker_configuration_errors() -> list[str]:
    settings = get_settings()
    errors = validate_runtime_settings(settings)
    if not settings.celery_broker_url.strip():
        errors.append("CELERY_BROKER_URL is required for a worker.")
    return errors


# Celery is an optional dependency of API-only development installs (`pip install -e .[worker]`).
try:  # pragma: no cover - exercised when the worker extra is installed
    from celery import Celery
    from celery.signals import worker_init

    celery_app = Celery("hpip", include=["app.workers.tasks"])
    celery_app.conf.update(celery_config())

    @worker_init.connect
    def _refuse_invalid_worker_configuration(**_kwargs) -> None:
        settings = get_settings()
        errors = worker_configuration_errors()
        if errors and (settings.is_production or not settings.celery_broker_url.strip()):
            raise RuntimeError("Worker configuration is invalid: " + " ".join(errors))

except ImportError:  # pragma: no cover
    celery_app = None

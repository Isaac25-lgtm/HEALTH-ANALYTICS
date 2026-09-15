from uuid import UUID

from app.config import get_settings
from app.db.session import get_session_factory
from app.services.export_jobs import ExportAttempt, process_export_job
from app.services.purge import PurgeFailed, purge_expired, raise_for_failures
from app.services.sync import execute_sync_job
from app.workers.celery_app import (
    EXPORT_TASK_NAME,
    PROBE_TASK_NAME,
    PURGE_TASK_NAME,
    SYNC_TASK_NAME,
    celery_app,
)


def run_execute_sync_job(job_id: str) -> str:
    session = get_session_factory()()
    try:
        job = execute_sync_job(session, UUID(job_id))
        session.commit()
        return job.status
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def run_generate_export_job(job_id: str) -> ExportAttempt:
    """One claimed export attempt with its own sessions. Safe under duplicate delivery."""
    return process_export_job(UUID(job_id), factory=get_session_factory(), auto_retry=True)


PURGE_MAX_RETRIES = 2


def purge_retry_countdown(retries: int) -> int:
    return min(60 * (retries + 1), 600)


def run_purge_expired_data(
    policies: list[str] | None = None, dry_run: bool | None = None, attempt: int = 1
) -> list[dict]:
    """Retention purge through the same service the CLI and scheduled job use.

    Raises PurgeFailed after the failure is recorded, so the task itself fails and retries.
    """
    session = get_session_factory()()
    try:
        results = purge_expired(session, policy_names=policies, dry_run=dry_run, source="scheduler", attempt=attempt)
        raise_for_failures(results)
        return [item.as_dict() for item in results]
    finally:
        session.close()


if celery_app is not None:

    @celery_app.task(name=SYNC_TASK_NAME, bind=True, max_retries=3)
    def execute_sync_job_task(self, job_id: str) -> str:
        try:
            return run_execute_sync_job(job_id)
        except Exception as exc:  # noqa: BLE001
            raise self.retry(exc=exc, countdown=min(2 ** self.request.retries, 30)) from exc

    @celery_app.task(name=EXPORT_TASK_NAME, bind=True, acks_late=True, reject_on_worker_lost=True)
    def generate_export_job_task(self, job_id: str) -> dict:
        attempt = run_generate_export_job(job_id)
        if attempt.outcome == "retry":
            # The persisted attempt counter is the real bound; max_retries is a second guard.
            raise self.retry(countdown=attempt.countdown, max_retries=get_settings().export_max_attempts)
        return attempt.as_dict()

    @celery_app.task(name=PURGE_TASK_NAME, bind=True, max_retries=PURGE_MAX_RETRIES)
    def purge_expired_data_task(self, policies: list[str] | None = None, dry_run: bool | None = None) -> list[dict]:
        attempt = self.request.retries + 1
        try:
            return run_purge_expired_data(policies, dry_run, attempt)
        except PurgeFailed as exc:
            # Retry only the policies that failed; completed policies are not repeated.
            raise self.retry(
                exc=exc,
                args=(),
                kwargs={"policies": exc.policies, "dry_run": dry_run},
                countdown=purge_retry_countdown(self.request.retries),
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise self.retry(exc=exc, countdown=purge_retry_countdown(self.request.retries)) from exc

    @celery_app.task(name=PROBE_TASK_NAME)
    def queue_health_probe(nonce: str) -> str:
        return str(nonce)[:64]

else:

    def execute_sync_job_task(job_id: str) -> str:
        return run_execute_sync_job(job_id)

    def generate_export_job_task(job_id: str) -> dict:
        return run_generate_export_job(job_id).as_dict()

    def purge_expired_data_task(policies: list[str] | None = None, dry_run: bool | None = None) -> list[dict]:
        return run_purge_expired_data(policies, dry_run)

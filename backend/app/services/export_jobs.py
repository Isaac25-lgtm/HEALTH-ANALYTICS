"""Export job lifecycle: idempotent submission, queue dispatch, worker claims, durable failure.

Flow
----
1. ``submit_export`` validates access, loads the displayed snapshot and returns the single
   live job for user + snapshot + export type, creating it only when none exists.
2. The API commits the job and its audit record, then calls ``start_export_job``. Production
   dispatches to Celery; in-request generation happens only when ``EXPORT_EAGER=true`` is set
   explicitly in development or test.
3. ``process_export_job`` (worker, or eager dev/test) claims the job atomically, writes the
   artifact from the committed snapshot to a temporary file, and publishes it only while it
   still holds the claim. Duplicate deliveries and stale claims cannot create a second
   artifact.
4. Any failure rolls back the work in progress and records ``status=failed`` with a safe
   ``error_code`` in a clean transaction. Retries are bounded by ``EXPORT_MAX_ATTEMPTS``; a
   permanently failed job releases its live key but stays visible in job history.
"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings, queue_configuration_errors
from app.domain.enums import ActionPermission, JobStatus
from app.domain.exports import EXPORT_FORMATS, export_label
from app.domain.modules import MODULE_PROGRAMME
from app.models import AuditLog, ExportJob, Programme, User
from app.services import artifact_store
from app.services.analysis import load_snapshot
from app.services.authorization import (
    AuthorizationError,
    require_action,
    require_org_unit_access,
    require_programme_access,
)
from app.services.evidence import evidence_package
from app.services.publishing import TEMPLATE_VERSION, export_output_dir, write_artifact
from app.services.rate_limit import check_rate
from app.version import SOFTWARE_VERSION

EXPORT_TASK_NAME = "app.workers.tasks.generate_export_job"

DISPATCH_PENDING = "pending"
DISPATCH_DISPATCHED = "dispatched"
DISPATCH_EAGER = "eager"
DISPATCH_FAILED = "enqueue_failed"
DISPATCH_LEGACY = "legacy"

ENQUEUE_FAILED = "export_enqueue_failed"
QUEUE_UNCONFIGURED = "export_queue_unconfigured"
GENERATION_FAILED = "export_generation_failed"
SNAPSHOT_UNAVAILABLE = "export_snapshot_unavailable"
NOT_AUTHORISED = "export_not_authorised"

DISPATCH_ERROR_CODES = frozenset({ENQUEUE_FAILED, QUEUE_UNCONFIGURED})

# Client-safe text. Never exception messages, tracebacks, file paths or configuration values.
SAFE_ERROR_MESSAGES = {
    ENQUEUE_FAILED: "The export could not be submitted to the worker queue. It can be retried.",
    QUEUE_UNCONFIGURED: "The export worker queue is not configured. Ask an administrator to check the service.",
    GENERATION_FAILED: "The export file could not be generated.",
    SNAPSHOT_UNAVAILABLE: "The analytical snapshot for this export is no longer available to you.",
    NOT_AUTHORISED: "You are no longer authorised to generate this export.",
}


class ExportGenerationError(RuntimeError):
    """Raised by the synchronous compatibility wrapper when an attempt did not succeed."""

    def __init__(self, error_code: str | None) -> None:
        self.error_code = error_code or GENERATION_FAILED
        super().__init__(SAFE_ERROR_MESSAGES.get(self.error_code, "Export generation failed."))


class ExportUnavailable(RuntimeError):
    code = "export_no_verified_data"

    def __init__(self) -> None:
        super().__init__(
            "This snapshot has no calculated values to export. Refresh governed source data "
            "and resolve configuration blockers first."
        )


@dataclass
class ExportSubmission:
    job: ExportJob
    created: bool
    reused: bool
    needs_dispatch: bool


@dataclass
class ExportAttempt:
    job_id: str
    outcome: str  # succeeded | failed | retry | skipped
    status: str | None
    error_code: str | None = None
    countdown: int | None = None
    attempt_count: int | None = None
    reason: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def _now() -> datetime:
    return datetime.now(UTC)


def record_operational_event(event_type: str, **fields) -> None:
    # Imported lazily: observability imports the DHIS2 package, which imports observability.
    from app.services.observability import record_operational_event as record

    record(event_type, **fields)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def export_idempotency_key(user_id: UUID, snapshot_id: UUID, export_type: str) -> str:
    return f"{user_id}:{snapshot_id}:{export_type}"


def _programme_id(session: Session, code: str) -> UUID | None:
    row = session.scalar(select(Programme).where(Programme.code == code))
    return row.id if row else None


def _live_job(session: Session, key: str) -> ExportJob | None:
    return session.scalar(select(ExportJob).where(ExportJob.active_key == key))


def _lease_expired(moment: datetime | None) -> bool:
    if moment is None:
        return True
    lease = timedelta(seconds=get_settings().export_job_lease_seconds)
    return _aware(moment) < _now() - lease


def _requeue(job: ExportJob, *, artifact_missing: bool = False) -> None:
    job.status = JobStatus.QUEUED.value
    job.dispatch_state = DISPATCH_PENDING
    job.error_code = None
    job.retry_scheduled = False
    job.claim_token = None
    job.finished_at = None
    if artifact_missing:
        job.file_path = None
        job.checksum = None
        job.artifact_storage = None
        job.artifact_expires_at = None
        job.artifact_deleted_at = None


def _resubmission(session: Session, job: ExportJob) -> ExportSubmission:
    """Decide what an identical request means for the existing live job."""
    if job.status == JobStatus.SUCCEEDED.value:
        if not artifact_store.is_expired(job) and artifact_store.is_available(session, job):
            return ExportSubmission(job, created=False, reused=True, needs_dispatch=False)
        # Expired or lost bytes: regenerate from the same committed snapshot.
        artifact_store.discard(session, job)
        _requeue(job, artifact_missing=True)
        return ExportSubmission(job, created=False, reused=True, needs_dispatch=True)
    if job.status == JobStatus.QUEUED.value:
        # Claims make a duplicate dispatch harmless, so a job that no worker can be holding is re-sent.
        stalled = job.dispatch_state in {DISPATCH_PENDING, DISPATCH_LEGACY, DISPATCH_EAGER} or (
            job.dispatch_state == DISPATCH_DISPATCHED and _lease_expired(job.dispatched_at)
        )
        if stalled:
            job.dispatch_state = DISPATCH_PENDING
        return ExportSubmission(job, created=False, reused=True, needs_dispatch=stalled)
    if job.status == JobStatus.RUNNING.value:
        stale = _lease_expired(job.claimed_at)
        if stale:
            _requeue(job)
        return ExportSubmission(job, created=False, reused=True, needs_dispatch=stale)
    # Failed while still holding the live key: a retry is permitted.
    if job.retry_scheduled and not _lease_expired(job.last_error_at):
        return ExportSubmission(job, created=False, reused=True, needs_dispatch=False)
    _requeue(job)
    return ExportSubmission(job, created=False, reused=True, needs_dispatch=True)


def submit_export(
    session: Session,
    *,
    user: User,
    export_type: str,
    org_unit_id: UUID,
    period: str,
    module: str | None = None,
    comparison_period: str | None = None,
    analysis_snapshot_id: UUID | None = None,
    view_hash: str | None = None,
) -> ExportSubmission:
    require_action(session, user, ActionPermission.EXPORT)
    require_org_unit_access(session, user, org_unit_id)
    if export_type not in EXPORT_FORMATS:
        raise AuthorizationError("invalid_input", "Unsupported export type.")
    if module:
        if module not in MODULE_PROGRAMME:
            raise AuthorizationError("invalid_input", "Analytical module is not recognised.")
        require_programme_access(session, user, MODULE_PROGRAMME[module])
    if analysis_snapshot_id is None:
        raise AuthorizationError(
            "snapshot_required",
            "Exports must name the displayed analytical snapshot. Recalculation is not permitted.",
        )
    check_rate(user.id, f"export:{export_type}", limit=get_settings().export_rate_limit)
    snapshot = load_snapshot(
        session,
        user=user,
        snapshot_id=analysis_snapshot_id,
        org_unit_id=org_unit_id,
        period=period,
        module=module,
        comparison_period=comparison_period,
        view_hash=view_hash,
    )
    dashboard = snapshot.payload_json or {}
    indicators = (dashboard.get("module_result") or {}).get("indicators") or []
    if not any(row.get("raw_value") is not None for row in indicators):
        raise ExportUnavailable()
    programme = MODULE_PROGRAMME[dashboard["module"]]
    require_programme_access(session, user, programme)
    key = export_idempotency_key(user.id, snapshot.id, export_type)
    live = _live_job(session, key)
    if live is not None:
        return _resubmission(session, live)
    package = snapshot.evidence_json or evidence_package(dashboard)
    run_id = dashboard.get("module_result", {}).get("current_run_id") or snapshot.current_run_id
    job = ExportJob(
        id=uuid4(),
        user_id=user.id,
        export_type=export_type,
        status=JobStatus.QUEUED.value,
        org_unit_id=org_unit_id,
        programme_id=_programme_id(session, programme),
        period=period,
        calculation_run_id=UUID(str(run_id)) if run_id else None,
        template_version=TEMPLATE_VERSION,
        module=dashboard.get("module") or snapshot.module,
        comparison_period=dashboard.get("comparison_period") or snapshot.comparison_period,
        analysis_snapshot_id=snapshot.id,
        view_hash=snapshot.view_hash,
        idempotency_key=key,
        active_key=key,
        attempt_count=0,
        max_attempts=get_settings().export_max_attempts,
        dispatch_state=DISPATCH_PENDING,
        retry_scheduled=False,
        metadata_json={
            "scope": package["scope"],
            "current_run_id": package["current_run_id"],
            "analysis_snapshot_id": str(snapshot.id),
            "view_hash": snapshot.view_hash,
            "software_version": SOFTWARE_VERSION,
        },
    )
    session.add(job)
    try:
        session.flush()
    except IntegrityError:
        # A concurrent identical request created the live job first; use that one.
        session.rollback()
        live = _live_job(session, key)
        if live is None:
            raise
        return _resubmission(session, live)
    return ExportSubmission(job, created=True, reused=False, needs_dispatch=True)


def request_export_retry(session: Session, *, user: User, job_id: UUID) -> ExportSubmission:
    job = session.get(ExportJob, job_id)
    if job is None or job.user_id != user.id:
        raise AuthorizationError("not_found", "Export job was not found.")
    require_action(session, user, ActionPermission.EXPORT)
    if job.org_unit_id:
        require_org_unit_access(session, user, job.org_unit_id)
    check_rate(user.id, "export:retry", limit=get_settings().export_rate_limit)
    if job.status == JobStatus.FAILED.value and job.active_key is None:
        raise AuthorizationError(
            "export_retry_not_permitted",
            "This export failed permanently. Request a new export from the snapshot.",
        )
    decision = _resubmission(session, job)
    if not decision.needs_dispatch:
        raise AuthorizationError(
            "export_retry_not_permitted",
            "This export is already queued, running, scheduled for retry, or complete.",
        )
    return decision


def send_export_task(job_id: UUID) -> str:
    """Publish the worker message. Raises when Celery or the broker is unavailable."""
    from app.workers.celery_app import celery_app

    if celery_app is None:
        raise RuntimeError("Celery is not installed in this runtime.")
    result = celery_app.send_task(
        EXPORT_TASK_NAME,
        args=[str(job_id)],
        queue=get_settings().export_queue_name,
    )
    return str(result.id)


def _mark_dispatch_failure(session: Session, job_id: UUID, code: str) -> None:
    session.execute(
        update(ExportJob)
        .where(ExportJob.id == job_id, ExportJob.status == JobStatus.QUEUED.value)
        .values(
            status=JobStatus.FAILED.value,
            error_code=code,
            dispatch_state=DISPATCH_FAILED,
            last_error_at=_now(),
            retry_scheduled=False,
        )
        .execution_options(synchronize_session=False)
    )
    session.commit()
    record_operational_event(code, job_id=str(job_id))


def start_export_job(session: Session, job_id: UUID) -> ExportJob:
    """Run or dispatch a committed job. Never call before the job and audit row are committed."""
    settings = get_settings()
    if settings.export_eager:
        if not settings.is_dev_or_test:
            _mark_dispatch_failure(session, job_id, QUEUE_UNCONFIGURED)
        else:
            session.execute(
                update(ExportJob)
                .where(ExportJob.id == job_id)
                .values(dispatch_state=DISPATCH_EAGER)
                .execution_options(synchronize_session=False)
            )
            session.commit()
            process_export_job(job_id, session=session, auto_retry=False)
        session.expire_all()
        return session.get(ExportJob, job_id)
    if not settings.celery_broker_url.strip() or queue_configuration_errors(settings):
        _mark_dispatch_failure(session, job_id, QUEUE_UNCONFIGURED)
    else:
        try:
            task_id = send_export_task(job_id)
        except Exception:  # noqa: BLE001 - broker errors are represented on the job, never raised raw
            session.rollback()
            _mark_dispatch_failure(session, job_id, ENQUEUE_FAILED)
        else:
            session.execute(
                update(ExportJob)
                .where(ExportJob.id == job_id)
                .values(dispatch_state=DISPATCH_DISPATCHED, celery_task_id=task_id, dispatched_at=_now())
                .execution_options(synchronize_session=False)
            )
            session.commit()
    session.expire_all()
    return session.get(ExportJob, job_id)


@contextmanager
def _unit_of_work(session: Session | None, factory: Callable[[], Session] | None) -> Iterator[Session]:
    if session is not None:
        yield session
        return
    if factory is None:
        from app.db.session import get_session_factory

        factory = get_session_factory()
    db = factory()
    try:
        yield db
    finally:
        db.close()


def _claim(db: Session, job_id: UUID, token: str) -> bool:
    now = _now()
    stale_before = now - timedelta(seconds=get_settings().export_job_lease_seconds)
    result = db.execute(
        update(ExportJob)
        .where(
            ExportJob.id == job_id,
            or_(
                ExportJob.status == JobStatus.QUEUED.value,
                and_(ExportJob.status == JobStatus.FAILED.value, ExportJob.active_key.is_not(None)),
                and_(ExportJob.status == JobStatus.RUNNING.value, ExportJob.claimed_at < stale_before),
            ),
        )
        .values(
            status=JobStatus.RUNNING.value,
            claim_token=token,
            claimed_at=now,
            started_at=now,
            attempt_count=ExportJob.attempt_count + 1,
            error_code=None,
            retry_scheduled=False,
        )
        .execution_options(synchronize_session=False)
    )
    db.commit()
    return result.rowcount == 1


ARTIFACT_TOO_LARGE = "export_artifact_too_large"
SAFE_ERROR_MESSAGES[ARTIFACT_TOO_LARGE] = (
    "The generated export is larger than this deployment allows. Narrow the export and try again."
)


def _classify(exc: Exception) -> tuple[str, bool]:
    """Return a safe error code and whether the failure is permanent."""
    if isinstance(exc, artifact_store.ArtifactError):
        if exc.code == artifact_store.ARTIFACT_TOO_LARGE:
            return ARTIFACT_TOO_LARGE, True
        return GENERATION_FAILED, False
    if isinstance(exc, AuthorizationError):
        if exc.code in {"not_found", "snapshot_mismatch", "snapshot_conflict"}:
            return SNAPSHOT_UNAVAILABLE, True
        return NOT_AUTHORISED, True
    return GENERATION_FAILED, False


def _backoff(attempt: int) -> int:
    settings = get_settings()
    delay = settings.export_retry_backoff_seconds * (2 ** max(attempt - 1, 0))
    return int(min(delay, settings.export_retry_backoff_max_seconds))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _audit(db: Session, job: ExportJob, action: str, after: dict) -> None:
    db.add(
        AuditLog(
            actor_user_id=None,
            action=action,
            resource_type="export_job",
            resource_id=str(job.id),
            after_json={"requested_by_user_id": str(job.user_id), "export_type": job.export_type, **after},
        )
    )


def _generate(db: Session, job_id: UUID, token: str, temp_holder: list[Path]) -> ExportAttempt:
    job = db.get(ExportJob, job_id)
    if job is None:
        return ExportAttempt(str(job_id), "skipped", None, reason="not_found")
    user = db.get(User, job.user_id)
    if user is None or not user.is_active:
        raise AuthorizationError("unauthenticated", "Export owner is not active.")
    require_action(db, user, ActionPermission.EXPORT)
    snapshot = load_snapshot(
        db,
        user=user,
        snapshot_id=job.analysis_snapshot_id,
        org_unit_id=job.org_unit_id,
        period=job.period or "",
        module=job.module,
        comparison_period=job.comparison_period,
        view_hash=job.view_hash,
    )
    dashboard = snapshot.payload_json or {}
    package = snapshot.evidence_json or evidence_package(dashboard)
    settings = get_settings()
    directory = export_output_dir()
    temp_path = directory / f".{job.id}.{token}.partial"
    temp_holder.append(temp_path)
    write_artifact(job.export_type, dashboard, package, temp_path)
    checksum = _sha256(temp_path)
    size = temp_path.stat().st_size
    if size > settings.export_artifact_max_bytes:
        raise artifact_store.ArtifactError(artifact_store.ARTIFACT_TOO_LARGE)
    storage = artifact_store.active_storage(settings)
    finished = _now()
    expires_at = artifact_store.artifact_expiry(settings, finished)
    media_type = artifact_store.media_type_for(job.export_type)
    final_path = directory / artifact_store.artifact_filename(job)
    published = db.execute(
        update(ExportJob)
        .where(
            ExportJob.id == job_id,
            ExportJob.claim_token == token,
            ExportJob.status == JobStatus.RUNNING.value,
        )
        .values(
            status=JobStatus.SUCCEEDED.value,
            file_path=str(final_path) if storage == artifact_store.STORAGE_FILESYSTEM else None,
            checksum=checksum,
            finished_at=finished,
            claim_token=None,
            error_code=None,
            retry_scheduled=False,
            artifact_storage=storage,
            artifact_media_type=media_type,
            artifact_size_bytes=size,
            artifact_expires_at=expires_at,
            artifact_deleted_at=None,
        )
        .execution_options(synchronize_session=False)
    )
    if published.rowcount != 1:
        # Another worker took over after the lease expired. Its artifact wins; ours is discarded.
        db.rollback()
        temp_path.unlink(missing_ok=True)
        return ExportAttempt(str(job_id), "skipped", None, reason="claim_lost")
    db.refresh(job)
    _audit(db, job, "export_generated", {"checksum": checksum, "attempt": job.attempt_count})
    # The row stays locked by the UPDATE until commit, so no other claimant can publish now.
    artifact_store.publish(db, job, temp_path, checksum=checksum, settings=settings, now=finished)
    db.commit()
    return ExportAttempt(
        str(job_id),
        "succeeded",
        JobStatus.SUCCEEDED.value,
        attempt_count=job.attempt_count,
    )


def _record_failure(db: Session, job_id: UUID, token: str, code: str, permanent: bool, auto_retry: bool):
    db.expire_all()
    job = db.get(ExportJob, job_id)
    if job is None:
        return ExportAttempt(str(job_id), "skipped", None, reason="not_found")
    if job.claim_token != token:
        return ExportAttempt(str(job_id), "skipped", job.status, reason="claim_lost")
    limit = job.max_attempts or get_settings().export_max_attempts
    final = permanent or job.attempt_count >= limit
    now = _now()
    job.status = JobStatus.FAILED.value
    job.error_code = code
    job.claim_token = None
    job.last_error_at = now
    job.retry_scheduled = bool(auto_retry and not final)
    if final:
        job.active_key = None
        job.finished_at = now
    _audit(db, job, "export_failed", {"error_code": code, "attempt": job.attempt_count, "permanent": final})
    db.commit()
    if job.retry_scheduled:
        return ExportAttempt(
            str(job_id),
            "retry",
            job.status,
            error_code=code,
            countdown=_backoff(job.attempt_count),
            attempt_count=job.attempt_count,
        )
    return ExportAttempt(str(job_id), "failed", job.status, error_code=code, attempt_count=job.attempt_count)


def process_export_job(
    job_id: UUID,
    *,
    session: Session | None = None,
    factory: Callable[[], Session] | None = None,
    auto_retry: bool = True,
) -> ExportAttempt:
    """Generate one export attempt. Workers pass ``factory``; eager dev/test passes ``session``."""
    token = secrets.token_hex(16)
    with _unit_of_work(session, factory) as db:
        if not _claim(db, job_id, token):
            db.expire_all()
            job = db.get(ExportJob, job_id)
            return ExportAttempt(
                str(job_id),
                "skipped",
                job.status if job else None,
                reason="not_claimable" if job else "not_found",
            )
    temp_holder: list[Path] = []
    try:
        with _unit_of_work(session, factory) as db:
            return _generate(db, job_id, token, temp_holder)
    except Exception as exc:  # noqa: BLE001 - every failure becomes a durable, safe job state
        code, permanent = _classify(exc)
        for path in temp_holder:
            path.unlink(missing_ok=True)
        if session is not None:
            session.rollback()
        record_operational_event(
            "export_attempt_failed",
            job_id=str(job_id),
            payload={"error_code": code, "exception_type": type(exc).__name__},
        )
        with _unit_of_work(session, factory) as db:
            return _record_failure(db, job_id, token, code, permanent, auto_retry)


def export_job_payload(job: ExportJob, session: Session | None = None) -> dict:
    """Client-safe job representation. File paths and exception details are never included."""
    failed = job.status == JobStatus.FAILED.value
    expired = job.status == JobStatus.SUCCEEDED.value and artifact_store.is_expired(job)
    available = (
        artifact_store.is_available(session, job)
        if session is not None
        else job.status == JobStatus.SUCCEEDED.value and not expired
    )
    return {
        "artifact_storage": job.artifact_storage,
        "artifact_expires_at": job.artifact_expires_at.isoformat() if job.artifact_expires_at else None,
        "artifact_expired": expired,
        "artifact_size_bytes": job.artifact_size_bytes,
        "media_type": job.artifact_media_type,
        "job_id": str(job.id),
        "status": job.status,
        "export_type": job.export_type,
        "label": export_label(job.export_type),
        "period": job.period,
        "module": job.module,
        "comparison_period": job.comparison_period,
        "calculation_run_id": str(job.calculation_run_id) if job.calculation_run_id else None,
        "analysis_snapshot_id": str(job.analysis_snapshot_id) if job.analysis_snapshot_id else None,
        "template_version": job.template_version,
        "downloadable": bool(available),
        "error_code": job.error_code,
        "error_message": SAFE_ERROR_MESSAGES.get(job.error_code) if job.error_code else None,
        "retryable": bool(failed and job.active_key is not None),
        "retry_scheduled": bool(job.retry_scheduled),
        "permanent_failure": bool(failed and job.active_key is None),
        "attempt_count": job.attempt_count,
        "max_attempts": job.max_attempts,
        "dispatch_state": job.dispatch_state,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "checksum": job.checksum if job.status == JobStatus.SUCCEEDED.value else None,
    }

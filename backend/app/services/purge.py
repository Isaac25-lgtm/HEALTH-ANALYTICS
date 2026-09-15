"""Retention purge service — the single implementation behind the CLI, the Celery task and
any scheduled command.

Properties:
- idempotent and safe to rerun; a second pass finds nothing left to do;
- bounded by PURGE_BATCH_SIZE and PURGE_MAX_BATCHES, committing per batch so a failure
  leaves completed batches durably deleted and the run restartable;
- guarded by a provider-neutral lease that is renewed inside every batch transaction with a
  holder-checked update, so a long purge keeps its lease and a purge that has lost it stops
  before deleting anything further;
- honest about file deletion: a file that was deleted or was already absent counts as gone,
  but a file that could not be deleted keeps its path, its job and its retry path, and fails
  the policy so the scheduler retries it;
- genuinely non-mutating in dry-run mode (it writes nothing at all, not even a run record);
- records counts and safe codes only, never deleted content, event UIDs, file paths or
  exception messages.

A failed policy is recorded in ``maintenance_runs`` and returned with ``status=failed``;
callers that run on a schedule use :func:`raise_for_failures` so the execution itself fails
and enters bounded retry.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.domain import retention as policies
from app.domain.enums import JobStatus
from app.models import (
    AiRequest,
    AnalysisSnapshot,
    AuditLog,
    CalculatedValue,
    CalculationRun,
    DataQualityFlag,
    ExportArtifact,
    ExportJob,
    MaintenanceLock,
    MaintenanceRun,
    OperationalEvent,
    RawAggregateValue,
    RawEventSnapshot,
)
from app.version import SOFTWARE_VERSION

TASK_TYPE = "retention_purge"
TERMINAL_JOB_STATUSES = (JobStatus.SUCCEEDED.value, JobStatus.FAILED.value, JobStatus.CANCELLED.value)

STATUS_COMPLETED = "completed"
STATUS_DISABLED = "disabled"
STATUS_LOCKED = "skipped_locked"
STATUS_FAILED = "failed"

ERROR_PURGE_FAILED = "purge_failed"
ERROR_ARTIFACT_DELETE_FAILED = "artifact_delete_failed"
ERROR_LEASE_LOST = "lease_lost"

FILE_DELETED = "deleted"
FILE_ABSENT = "absent"
FILE_FAILED = "failed"


@dataclass
class PurgeResult:
    policy: str
    entity: str
    status: str
    dry_run: bool
    cutoff: datetime | None = None
    rows_examined: int = 0
    rows_deleted: int = 0
    files_examined: int = 0
    files_deleted: int = 0
    files_absent: int = 0
    files_failed: int = 0
    rows_skipped: int = 0
    batches: int = 0
    attempt: int = 1
    error_code: str | None = None
    error_summary: str | None = None
    run_id: str | None = None
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        data = asdict(self)
        data["cutoff"] = self.cutoff.isoformat() if self.cutoff else None
        return data


class PurgeAborted(Exception):
    """A policy stopped for a known, safe reason. The code and summary are safe to persist."""

    def __init__(self, code: str, summary: str) -> None:
        self.code = code
        self.summary = summary
        super().__init__(code)


class LeaseLost(PurgeAborted):
    def __init__(self) -> None:
        super().__init__(ERROR_LEASE_LOST, "The policy lease was lost; the purge stopped before the next batch.")


class PurgeFailed(RuntimeError):
    """Raised by scheduled callers when at least one policy failed. Carries only policy names
    and safe codes, and is rebuildable from its arguments so a task result backend keeps it."""

    def __init__(self, policies: list[str], codes: list[str]) -> None:
        self.policies = list(policies)
        self.codes = list(codes)
        super().__init__(self.policies, self.codes)

    @classmethod
    def from_results(cls, results: Iterable[PurgeResult]) -> PurgeFailed:
        failed = [item for item in results if item.status == STATUS_FAILED]
        return cls([item.policy for item in failed], sorted({item.error_code or ERROR_PURGE_FAILED for item in failed}))

    def __str__(self) -> str:
        return f"Retention purge failed for: {', '.join(self.policies)} ({', '.join(self.codes)})"


def _now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# Lease
# ---------------------------------------------------------------------------


def acquire_lease(session: Session, name: str, holder: str, ttl_seconds: int, now: datetime | None = None) -> bool:
    """Take the named lease. Returns False when another live holder has it."""
    moment = now or _now()
    expires = moment + timedelta(seconds=ttl_seconds)
    existing = session.get(MaintenanceLock, name)
    if existing is None:
        session.add(MaintenanceLock(name=name, holder=holder, acquired_at=moment, expires_at=expires))
        try:
            session.commit()
            return True
        except IntegrityError:
            session.rollback()
            return False
    taken = session.execute(
        update(MaintenanceLock)
        .where(MaintenanceLock.name == name, MaintenanceLock.expires_at < moment)
        .values(holder=holder, acquired_at=moment, expires_at=expires)
        .execution_options(synchronize_session=False)
    )
    session.commit()
    return taken.rowcount == 1


def renew_lease(session: Session, name: str, holder: str, ttl_seconds: int, now: datetime | None = None) -> bool:
    """Extend the lease only if this holder still owns it. Does not commit.

    Run inside the batch transaction: on PostgreSQL the row lock taken here is held until the
    batch commits, so a competing takeover waits and then sees the renewed expiry.
    """
    moment = now or _now()
    renewed = session.execute(
        update(MaintenanceLock)
        .where(MaintenanceLock.name == name, MaintenanceLock.holder == holder)
        .values(expires_at=moment + timedelta(seconds=ttl_seconds))
        .execution_options(synchronize_session=False)
    )
    return renewed.rowcount == 1


def release_lease(session: Session, name: str, holder: str) -> None:
    session.execute(
        delete(MaintenanceLock)
        .where(MaintenanceLock.name == name, MaintenanceLock.holder == holder)
        .execution_options(synchronize_session=False)
    )
    session.commit()


@dataclass
class LeaseGuard:
    """Heartbeat handed to policy handlers. ``renew`` must be the first write of each batch."""

    session: Session
    name: str
    holder: str
    ttl_seconds: int
    active: bool = True

    def renew(self) -> None:
        if not self.active:
            return
        if not renew_lease(self.session, self.name, self.holder, self.ttl_seconds):
            self.session.rollback()
            raise LeaseLost()


def _no_lease(session: Session) -> LeaseGuard:
    return LeaseGuard(session=session, name="", holder="", ttl_seconds=0, active=False)


# ---------------------------------------------------------------------------
# Batch and file helpers
# ---------------------------------------------------------------------------


def _ids(session: Session, statement, limit: int) -> list:
    return list(session.scalars(statement.limit(limit)).all())


def _delete_by_ids(session: Session, model, ids: Iterable) -> int:
    values = list(ids)
    if not values:
        return 0
    result = session.execute(
        delete(model).where(model.id.in_(values)).execution_options(synchronize_session=False)
    )
    return int(result.rowcount or 0)


def _unlink(path: Path) -> str:
    """Remove one artifact file: deleted, already absent, or failed (never raised, never hidden)."""
    try:
        path.unlink()
        return FILE_DELETED
    except FileNotFoundError:
        return FILE_ABSENT
    except OSError:
        return FILE_FAILED


def _count_file(result: PurgeResult, outcome: str) -> None:
    if outcome == FILE_DELETED:
        result.files_deleted += 1
    elif outcome == FILE_ABSENT:
        result.files_absent += 1
    else:
        result.files_failed += 1


def _fail_for_files(result: PurgeResult) -> None:
    if result.files_failed:
        raise PurgeAborted(
            ERROR_ARTIFACT_DELETE_FAILED,
            f"{result.files_failed} artifact file(s) could not be deleted and were kept for retry.",
        )


# ---------------------------------------------------------------------------
# Policy handlers. Each renews the lease and commits per batch.
# ---------------------------------------------------------------------------

Handler = Callable[[Session, datetime, PurgeResult, Settings, LeaseGuard], None]


def _purge_raw_aggregates(
    session: Session, cutoff: datetime, result: PurgeResult, settings: Settings, lease: LeaseGuard
) -> None:
    expired = RawAggregateValue.extracted_at < cutoff
    statement = select(RawAggregateValue.id).where(expired).order_by(RawAggregateValue.id)
    result.rows_examined = int(
        session.scalar(select(func.count()).select_from(RawAggregateValue).where(expired)) or 0
    )
    if result.dry_run:
        return
    for _ in range(settings.purge_max_batches):
        batch = _ids(session, statement, settings.purge_batch_size)
        if not batch:
            break
        lease.renew()
        # A retained row may still point at a row in this batch; drop the pointer first.
        session.execute(
            update(RawAggregateValue)
            .where(RawAggregateValue.superseded_by_id.in_(batch))
            .values(superseded_by_id=None)
            .execution_options(synchronize_session=False)
        )
        result.rows_deleted += _delete_by_ids(session, RawAggregateValue, batch)
        result.batches += 1
        session.commit()


def _purge_mpdsr_events(
    session: Session, cutoff: datetime, result: PurgeResult, settings: Settings, lease: LeaseGuard
) -> None:
    expired = RawEventSnapshot.extracted_at < cutoff
    statement = select(RawEventSnapshot.id).where(expired).order_by(RawEventSnapshot.id)
    result.rows_examined = int(
        session.scalar(select(func.count()).select_from(RawEventSnapshot).where(expired)) or 0
    )
    if result.dry_run:
        return
    for _ in range(settings.purge_max_batches):
        batch = _ids(session, statement, settings.purge_batch_size)
        if not batch:
            break
        lease.renew()
        uids = list(session.scalars(select(RawEventSnapshot.event_uid).where(RawEventSnapshot.id.in_(batch))).all())
        # Temporary event UIDs must not survive the event cache anywhere, including flags.
        if uids:
            session.execute(
                update(DataQualityFlag)
                .where(DataQualityFlag.event_uid.in_(uids))
                .values(event_uid=None)
                .execution_options(synchronize_session=False)
            )
        session.execute(
            update(RawEventSnapshot)
            .where(RawEventSnapshot.superseded_by_id.in_(batch))
            .values(superseded_by_id=None)
            .execution_options(synchronize_session=False)
        )
        result.rows_deleted += _delete_by_ids(session, RawEventSnapshot, batch)
        result.batches += 1
        session.commit()


def _purge_export_files(
    session: Session, cutoff: datetime, result: PurgeResult, settings: Settings, lease: LeaseGuard
) -> None:
    """Delete expired bytes, keeping the job, checksum and size so a later download can
    explain itself as ``artifact_expired`` instead of returning a bare 404.

    A filesystem file that cannot be deleted keeps its path and its un-deleted state, so the
    next attempt retries it; the policy then fails once the remaining work is done.
    """
    moment = _now()
    expired = and_(
        ExportJob.artifact_expires_at.is_not(None),
        ExportJob.artifact_expires_at <= moment,
        ExportJob.artifact_deleted_at.is_(None),
    )
    result.files_examined = int(session.scalar(select(func.count()).select_from(ExportJob).where(expired)) or 0)
    if result.dry_run:
        return
    kept: set[UUID] = set()
    for _ in range(settings.purge_max_batches):
        statement = select(ExportJob.id).where(expired).order_by(ExportJob.id)
        if kept:
            statement = statement.where(ExportJob.id.not_in(kept))
        batch = _ids(session, statement, settings.purge_batch_size)
        if not batch:
            break
        lease.renew()
        for job in session.scalars(select(ExportJob).where(ExportJob.id.in_(batch))).all():
            if job.artifact_storage == "filesystem" and job.file_path:
                outcome = _unlink(Path(job.file_path))
                _count_file(result, outcome)
                if outcome == FILE_FAILED:
                    kept.add(job.id)
                    continue
                job.file_path = None
            else:
                removed = session.execute(
                    delete(ExportArtifact)
                    .where(ExportArtifact.export_job_id == job.id)
                    .execution_options(synchronize_session=False)
                )
                result.files_deleted += int(removed.rowcount or 0)
            job.artifact_deleted_at = moment
        result.batches += 1
        session.commit()
    # Bytes whose owning job was already removed or re-queued.
    lease.renew()
    orphaned = session.execute(
        delete(ExportArtifact)
        .where(ExportArtifact.expires_at <= moment)
        .execution_options(synchronize_session=False)
    )
    result.files_deleted += int(orphaned.rowcount or 0)
    session.commit()
    result.rows_skipped = len(kept)
    _fail_for_files(result)


def _purge_export_jobs(
    session: Session, cutoff: datetime, result: PurgeResult, settings: Settings, lease: LeaseGuard
) -> None:
    """Terminal job metadata only. Queued and running jobs are never purged by age.

    A job whose file could not be deleted is kept: its metadata is the only retry path to that
    file, so it never disappears before its file does.
    """
    terminal = ExportJob.status.in_(TERMINAL_JOB_STATUSES)
    aged = or_(
        ExportJob.finished_at < cutoff,
        and_(ExportJob.finished_at.is_(None), ExportJob.created_at < cutoff),
    )
    result.rows_examined = int(
        session.scalar(select(func.count()).select_from(ExportJob).where(terminal, aged)) or 0
    )
    if result.dry_run:
        return
    kept: set[UUID] = set()
    for _ in range(settings.purge_max_batches):
        statement = select(ExportJob.id).where(terminal, aged).order_by(ExportJob.id)
        if kept:
            statement = statement.where(ExportJob.id.not_in(kept))
        batch = _ids(session, statement, settings.purge_batch_size)
        if not batch:
            break
        lease.renew()
        deletable: list[UUID] = []
        for job in session.scalars(select(ExportJob).where(ExportJob.id.in_(batch))).all():
            if job.artifact_storage == "filesystem" and job.file_path:
                outcome = _unlink(Path(job.file_path))
                _count_file(result, outcome)
                if outcome == FILE_FAILED:
                    kept.add(job.id)
                    continue
            deletable.append(job.id)
        if deletable:
            session.execute(
                delete(ExportArtifact)
                .where(ExportArtifact.export_job_id.in_(deletable))
                .execution_options(synchronize_session=False)
            )
            result.rows_deleted += _delete_by_ids(session, ExportJob, deletable)
        result.batches += 1
        session.commit()
    result.rows_skipped = len(kept)
    _fail_for_files(result)


def _purge_snapshots(
    session: Session, cutoff: datetime, result: PurgeResult, settings: Settings, lease: LeaseGuard
) -> None:
    """Snapshots with their calculation runs, values, flags and AI request metadata.

    A snapshot still referenced by a retained export job is skipped rather than broken; it is
    removed once that export job passes its own 90-day metadata window.
    """
    expired = AnalysisSnapshot.created_at < cutoff
    result.rows_examined = int(
        session.scalar(select(func.count()).select_from(AnalysisSnapshot).where(expired)) or 0
    )
    if result.dry_run:
        return
    skipped: set[UUID] = set()
    for _ in range(settings.purge_max_batches):
        statement = select(AnalysisSnapshot.id).where(expired).order_by(AnalysisSnapshot.id)
        if skipped:
            statement = statement.where(AnalysisSnapshot.id.not_in(skipped))
        candidates = _ids(session, statement, settings.purge_batch_size)
        if not candidates:
            break
        referenced = {
            value
            for value in session.scalars(
                select(ExportJob.analysis_snapshot_id).where(ExportJob.analysis_snapshot_id.in_(candidates))
            ).all()
            if value is not None
        }
        batch = [value for value in candidates if value not in referenced]
        skipped.update(referenced)
        result.rows_skipped = len(skipped)
        if batch:
            lease.renew()
            run_ids = [
                value
                for value in session.scalars(
                    select(AnalysisSnapshot.current_run_id).where(AnalysisSnapshot.id.in_(batch))
                ).all()
                if value is not None
            ]
            session.execute(
                delete(AiRequest)
                .where(AiRequest.analysis_snapshot_id.in_(batch))
                .execution_options(synchronize_session=False)
            )
            result.rows_deleted += _delete_by_ids(session, AnalysisSnapshot, batch)
            _purge_runs(session, run_ids, result)
            result.batches += 1
            session.commit()
        else:
            session.commit()
            break
    # Calculation runs past the window that no retained snapshot or export job still needs.
    for _ in range(settings.purge_max_batches):
        orphans = _ids(
            session,
            select(CalculationRun.id)
            .where(
                CalculationRun.created_at < cutoff,
                CalculationRun.id.not_in(
                    select(AnalysisSnapshot.current_run_id).where(AnalysisSnapshot.current_run_id.is_not(None))
                ),
                CalculationRun.id.not_in(
                    select(ExportJob.calculation_run_id).where(ExportJob.calculation_run_id.is_not(None))
                ),
            )
            .order_by(CalculationRun.id),
            settings.purge_batch_size,
        )
        if not orphans:
            break
        lease.renew()
        _purge_runs(session, orphans, result)
        result.batches += 1
        session.commit()


def _purge_runs(session: Session, run_ids: list, result: PurgeResult) -> None:
    """Delete calculation runs and their dependents in foreign-key-safe order."""
    ids = [value for value in run_ids if value is not None]
    if not ids:
        return
    still_used = {
        value
        for value in session.scalars(
            select(AnalysisSnapshot.current_run_id).where(AnalysisSnapshot.current_run_id.in_(ids))
        ).all()
        if value is not None
    } | {
        value
        for value in session.scalars(
            select(ExportJob.calculation_run_id).where(ExportJob.calculation_run_id.in_(ids))
        ).all()
        if value is not None
    }
    ids = [value for value in ids if value not in still_used]
    if not ids:
        return
    for model, column in (
        (CalculatedValue, CalculatedValue.calculation_run_id),
        (DataQualityFlag, DataQualityFlag.calculation_run_id),
        (AiRequest, AiRequest.calculation_run_id),
    ):
        session.execute(delete(model).where(column.in_(ids)).execution_options(synchronize_session=False))
    result.rows_deleted += _delete_by_ids(session, CalculationRun, ids)


def _purge_audit_logs(
    session: Session, cutoff: datetime, result: PurgeResult, settings: Settings, lease: LeaseGuard
) -> None:
    expired = AuditLog.created_at < cutoff
    statement = select(AuditLog.id).where(expired).order_by(AuditLog.id)
    result.rows_examined = int(session.scalar(select(func.count()).select_from(AuditLog).where(expired)) or 0)
    if result.dry_run:
        return
    for _ in range(settings.purge_max_batches):
        batch = _ids(session, statement, settings.purge_batch_size)
        if not batch:
            break
        lease.renew()
        result.rows_deleted += _delete_by_ids(session, AuditLog, batch)
        result.batches += 1
        session.commit()


def _purge_operational_records(
    session: Session, cutoff: datetime, result: PurgeResult, settings: Settings, lease: LeaseGuard
) -> None:
    """Maintenance run records and operational events: counts and codes, never content."""
    targets = (
        (MaintenanceRun, MaintenanceRun.created_at < cutoff),
        (OperationalEvent, OperationalEvent.created_at < cutoff),
    )
    result.rows_examined = sum(
        int(session.scalar(select(func.count()).select_from(model).where(expired)) or 0) for model, expired in targets
    )
    if result.dry_run:
        return
    for model, expired in targets:
        statement = select(model.id).where(expired).order_by(model.id)
        for _ in range(settings.purge_max_batches):
            batch = _ids(session, statement, settings.purge_batch_size)
            if not batch:
                break
            lease.renew()
            result.rows_deleted += _delete_by_ids(session, model, batch)
            result.batches += 1
            session.commit()


HANDLERS: dict[str, Handler] = {
    policies.RAW_AGGREGATES: _purge_raw_aggregates,
    policies.MPDSR_EVENTS: _purge_mpdsr_events,
    policies.EXPORT_FILES: _purge_export_files,
    policies.EXPORT_JOBS: _purge_export_jobs,
    policies.SNAPSHOTS: _purge_snapshots,
    policies.AUDIT_LOGS: _purge_audit_logs,
    policies.OPERATIONAL_RECORDS: _purge_operational_records,
}


def _record_run(session: Session, result: PurgeResult, started: datetime, source: str) -> None:
    run = MaintenanceRun(
        id=uuid4(),
        task_type=TASK_TYPE,
        policy=result.policy,
        entity=result.entity,
        requested_cutoff=result.cutoff,
        started_at=started,
        finished_at=_now(),
        status=result.status,
        rows_examined=result.rows_examined,
        rows_deleted=result.rows_deleted,
        files_examined=result.files_examined,
        files_deleted=result.files_deleted,
        rows_skipped=result.rows_skipped,
        batches=result.batches,
        attempt=result.attempt,
        dry_run=result.dry_run,
        source=source,
        error_code=result.error_code,
        error_summary=result.error_summary,
        software_version=SOFTWARE_VERSION,
    )
    session.add(run)
    session.commit()
    result.run_id = str(run.id)


def purge_policy(
    session: Session,
    policy_name: str,
    *,
    settings: Settings | None = None,
    dry_run: bool | None = None,
    now: datetime | None = None,
    source: str = "cli",
    attempt: int = 1,
) -> PurgeResult:
    settings = settings or get_settings()
    policy = policies.POLICIES[policy_name]
    is_dry = settings.purge_dry_run if dry_run is None else dry_run
    result = PurgeResult(
        policy=policy.name, entity=policy.entity, status=STATUS_COMPLETED, dry_run=is_dry, attempt=attempt
    )
    if not settings.purge_enabled:
        result.status = STATUS_DISABLED
        result.notes.append("PURGE_ENABLED is false.")
        return result
    result.cutoff = policy.cutoff(settings, now)
    started = _now()
    if is_dry:
        # A dry run touches nothing: no lease, no deletions, no run record.
        HANDLERS[policy.name](session, result.cutoff, result, settings, _no_lease(session))
        return result
    holder = secrets.token_hex(8)
    lease = f"{TASK_TYPE}:{policy.name}"
    if not acquire_lease(session, lease, holder, settings.purge_lock_timeout_seconds, started):
        result.status = STATUS_LOCKED
        result.notes.append("Another maintenance process holds this policy lease.")
        return result
    guard = LeaseGuard(session=session, name=lease, holder=holder, ttl_seconds=settings.purge_lock_timeout_seconds)
    try:
        HANDLERS[policy.name](session, result.cutoff, result, settings, guard)
    except PurgeAborted as exc:
        session.rollback()
        result.status = STATUS_FAILED
        result.error_code = exc.code
        result.error_summary = exc.summary
    except Exception as exc:  # noqa: BLE001 - failures become safe codes, never raw exceptions
        session.rollback()
        result.status = STATUS_FAILED
        result.error_code = ERROR_PURGE_FAILED
        result.error_summary = type(exc).__name__
    finally:
        # Holder-checked: a purge that lost its lease cannot release the new holder's lease.
        release_lease(session, lease, holder)
        _record_run(session, result, started, source)
    return result


def purge_expired(
    session: Session,
    *,
    policy_names: Iterable[str] | None = None,
    settings: Settings | None = None,
    dry_run: bool | None = None,
    now: datetime | None = None,
    source: str = "cli",
    attempt: int = 1,
) -> list[PurgeResult]:
    """Run retention policies in dependency-safe order. A failed policy does not stop the others."""
    settings = settings or get_settings()
    names = list(policy_names) if policy_names else list(policies.POLICY_ORDER)
    unknown = [name for name in names if name not in policies.POLICIES]
    if unknown:
        raise ValueError(f"Unknown retention policy: {', '.join(sorted(unknown))}")
    ordered = [name for name in policies.POLICY_ORDER if name in names]
    return [
        purge_policy(session, name, settings=settings, dry_run=dry_run, now=now, source=source, attempt=attempt)
        for name in ordered
    ]


def failed_results(results: Iterable[PurgeResult]) -> list[PurgeResult]:
    return [item for item in results if item.status == STATUS_FAILED]


def raise_for_failures(results: list[PurgeResult]) -> list[PurgeResult]:
    """Scheduled callers: turn any failed policy into a failed execution (after it was recorded)."""
    if failed_results(results):
        raise PurgeFailed.from_results(results)
    return results

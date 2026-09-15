"""Purge failure semantics (corrective work package E).

A failed policy must fail the scheduled execution and retry; a file that cannot be deleted must
keep its path, its job and its retry path; a purge that loses its lease must stop.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update

from app.config import get_settings
from app.domain import retention
from app.models import (
    AuditLog,
    ExportArtifact,
    ExportJob,
    MaintenanceLock,
    MaintenanceRun,
    OperationalEvent,
    OrgUnit,
    User,
)
from app.services import purge
from app.services.purge import (
    ERROR_ARTIFACT_DELETE_FAILED,
    ERROR_LEASE_LOST,
    STATUS_COMPLETED,
    STATUS_FAILED,
    PurgeFailed,
    PurgeResult,
    purge_policy,
)
from app.workers import tasks
from scripts import purge_expired as purge_cli

PAST = datetime.now(UTC) - timedelta(hours=2)
LONG_AGO = datetime.now(UTC) - timedelta(days=400)


def _user_id(session):
    return session.scalar(select(User.id).where(User.username == "pader.focal"))


def _org_id(session):
    return session.scalar(select(OrgUnit.id).where(OrgUnit.code == "PADER"))


def _file_job(session, path: Path, *, expired_at=PAST, finished_at=None, content=b"xlsx") -> ExportJob:
    path.write_bytes(content)
    job = ExportJob(
        id=uuid4(),
        user_id=_user_id(session),
        org_unit_id=_org_id(session),
        export_type="excel",
        status="succeeded",
        file_path=str(path),
        artifact_storage="filesystem",
        artifact_expires_at=expired_at,
        finished_at=finished_at or datetime.now(UTC) - timedelta(days=1),
    )
    session.add(job)
    session.commit()
    return job


def _database_job(session, *, expired_at=PAST) -> ExportJob:
    job = ExportJob(
        id=uuid4(),
        user_id=_user_id(session),
        org_unit_id=_org_id(session),
        export_type="excel",
        status="succeeded",
        artifact_storage="database",
        artifact_expires_at=expired_at,
        finished_at=datetime.now(UTC) - timedelta(days=1),
    )
    session.add(job)
    session.flush()
    session.add(
        ExportArtifact(
            export_job_id=job.id, content=b"bytes", size_bytes=5, checksum="abc", expires_at=expired_at
        )
    )
    session.commit()
    return job


@pytest.fixture()
def undeletable(monkeypatch):
    """Make chosen paths raise PermissionError on unlink, as a locked or read-only file does."""
    blocked: set[str] = set()
    original = Path.unlink

    def guarded(self, *args, **kwargs):
        if str(self) in blocked:
            raise PermissionError(13, "Access is denied", str(self))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", guarded)
    return blocked


def _last_run(session, policy: str) -> MaintenanceRun:
    return session.scalars(
        select(MaintenanceRun).where(MaintenanceRun.policy == policy).order_by(MaintenanceRun.started_at.desc())
    ).first()


def _encoded(run: MaintenanceRun) -> str:
    return json.dumps({column.name: str(getattr(run, column.name)) for column in MaintenanceRun.__table__.columns})


# ---------------------------------------------------------------------------
# Files: deleted, already absent, failed
# ---------------------------------------------------------------------------


def test_unlink_permission_error_keeps_the_path_the_job_and_fails_the_policy(session, tmp_path, undeletable):
    locked = tmp_path / "locked-export.xlsx"
    job = _file_job(session, locked)
    undeletable.add(str(locked))

    result = purge_policy(session, retention.EXPORT_FILES, dry_run=False)

    assert result.status == STATUS_FAILED
    assert result.error_code == ERROR_ARTIFACT_DELETE_FAILED
    assert result.files_failed == 1 and result.files_deleted == 0
    session.expire_all()
    kept = session.get(ExportJob, job.id)
    assert kept.file_path == str(locked) and kept.artifact_deleted_at is None
    assert locked.exists()
    run = _last_run(session, retention.EXPORT_FILES)
    assert run.status == STATUS_FAILED and run.error_code == ERROR_ARTIFACT_DELETE_FAILED
    assert str(tmp_path) not in _encoded(run) and "Access is denied" not in _encoded(run)
    assert session.get(MaintenanceLock, "retention_purge:export_files") is None

    # Once the file can be deleted the retry path completes it.
    undeletable.clear()
    retry = purge_policy(session, retention.EXPORT_FILES, dry_run=False, attempt=2)
    assert retry.status == STATUS_COMPLETED and retry.files_deleted == 1
    session.expire_all()
    done = session.get(ExportJob, job.id)
    assert done.file_path is None and done.artifact_deleted_at is not None
    assert not locked.exists()
    assert _last_run(session, retention.EXPORT_FILES).attempt == 2


def test_an_already_absent_file_counts_as_gone(session, tmp_path):
    missing = tmp_path / "already-removed.xlsx"
    job = _file_job(session, missing)
    missing.unlink()

    result = purge_policy(session, retention.EXPORT_FILES, dry_run=False)

    assert result.status == STATUS_COMPLETED
    assert result.files_absent == 1 and result.files_failed == 0
    session.expire_all()
    marked = session.get(ExportJob, job.id)
    assert marked.file_path is None and marked.artifact_deleted_at is not None


def test_mixed_database_and_filesystem_artifacts_are_handled_independently(session, tmp_path, undeletable):
    stored = _database_job(session)
    ok_path, locked_path = tmp_path / "ok.xlsx", tmp_path / "locked.xlsx"
    ok_job = _file_job(session, ok_path)
    locked_job = _file_job(session, locked_path)
    undeletable.add(str(locked_path))

    result = purge_policy(session, retention.EXPORT_FILES, dry_run=False)

    assert result.status == STATUS_FAILED and result.files_failed == 1
    session.expire_all()
    assert session.scalar(select(func.count()).select_from(ExportArtifact)) == 0
    assert session.get(ExportJob, stored.id).artifact_deleted_at is not None
    assert session.get(ExportJob, ok_job.id).artifact_deleted_at is not None and not ok_path.exists()
    assert session.get(ExportJob, locked_job.id).artifact_deleted_at is None and locked_path.exists()


def test_job_metadata_never_disappears_before_its_file_and_partial_batches_resume(
    session, tmp_path, undeletable, monkeypatch
):
    monkeypatch.setattr(get_settings(), "purge_batch_size", 1)
    old = LONG_AGO
    paths = [tmp_path / f"old-{index}.xlsx" for index in range(3)]
    ids = [_file_job(session, path, expired_at=old, finished_at=old).id for path in paths]
    undeletable.add(str(paths[1]))

    first = purge_policy(session, retention.EXPORT_JOBS, dry_run=False)

    assert first.status == STATUS_FAILED and first.error_code == ERROR_ARTIFACT_DELETE_FAILED
    assert first.rows_deleted == 2 and first.rows_skipped == 1 and first.batches >= 3
    session.expire_all()
    remaining = session.scalars(select(ExportJob).where(ExportJob.id.in_(ids))).all()
    assert [row.id for row in remaining] == [ids[1]]
    assert remaining[0].file_path == str(paths[1]) and paths[1].exists()

    undeletable.clear()
    second = purge_policy(session, retention.EXPORT_JOBS, dry_run=False, attempt=2)
    assert second.status == STATUS_COMPLETED and second.rows_deleted == 1
    assert session.scalar(select(func.count()).where(ExportJob.id.in_(ids))) == 0
    assert not any(path.exists() for path in paths)


# ---------------------------------------------------------------------------
# Failure must fail the execution: Celery retry and CLI exit status
# ---------------------------------------------------------------------------


def _failing(policy: str) -> PurgeResult:
    return PurgeResult(
        policy=policy,
        entity="export_artifacts",
        status=STATUS_FAILED,
        dry_run=False,
        error_code=ERROR_ARTIFACT_DELETE_FAILED,
    )


def _completed(policy: str) -> PurgeResult:
    return PurgeResult(policy=policy, entity="x", status=STATUS_COMPLETED, dry_run=False)


def test_a_failed_policy_is_recorded_and_then_raised_for_the_scheduler(session, monkeypatch):
    def explode(*_args, **_kwargs):
        raise RuntimeError("disk at /srv/exports is gone")

    monkeypatch.setitem(purge.HANDLERS, retention.AUDIT_LOGS, explode)
    monkeypatch.setattr(tasks, "get_session_factory", lambda: lambda: session)
    with pytest.raises(PurgeFailed) as raised:
        tasks.run_purge_expired_data([retention.AUDIT_LOGS, retention.RAW_AGGREGATES], None, attempt=1)
    assert raised.value.policies == [retention.AUDIT_LOGS]
    assert "/srv/exports" not in str(raised.value)
    # The failure record was committed before the exception left the service.
    run = _last_run(session, retention.AUDIT_LOGS)
    assert run.status == STATUS_FAILED and run.error_summary == "RuntimeError"
    assert _last_run(session, retention.RAW_AGGREGATES).status == STATUS_COMPLETED


@pytest.mark.skipif(tasks.celery_app is None, reason="Celery is not installed")
def test_celery_task_retries_only_failed_policies_and_finally_fails(monkeypatch):
    calls: list[tuple[list[str] | None, int]] = []

    def always_failing(policies=None, dry_run=None, attempt=1):
        calls.append((policies, attempt))
        raise PurgeFailed.from_results([_completed(retention.RAW_AGGREGATES), _failing(retention.EXPORT_FILES)])

    monkeypatch.setattr(tasks, "run_purge_expired_data", always_failing)
    outcome = tasks.purge_expired_data_task.apply(kwargs={"policies": None, "dry_run": False})
    assert outcome.state == "FAILURE"
    # Celery may rebuild the exception from its arguments; either way it names the failed policy.
    assert "export_files" in str(outcome.result)
    assert [attempt for _policies, attempt in calls] == [1, 2, 3]
    assert calls[0][0] is None
    assert all(policies == [retention.EXPORT_FILES] for policies, _attempt in calls[1:])


@pytest.mark.skipif(tasks.celery_app is None, reason="Celery is not installed")
def test_celery_task_succeeds_when_a_retry_clears_the_failure(monkeypatch):
    attempts: list[int] = []

    def flaky(policies=None, dry_run=None, attempt=1):
        attempts.append(attempt)
        if attempt == 1:
            raise PurgeFailed.from_results([_failing(retention.EXPORT_JOBS)])
        return [_completed(retention.EXPORT_JOBS).as_dict()]

    monkeypatch.setattr(tasks, "run_purge_expired_data", flaky)
    outcome = tasks.purge_expired_data_task.apply(kwargs={"policies": None, "dry_run": False})
    assert outcome.state == "SUCCESS"
    assert attempts == [1, 2]


def test_cli_exits_non_zero_when_a_requested_policy_fails(session, monkeypatch, capsys):
    monkeypatch.setattr(purge_cli, "get_session_factory", lambda: lambda: session)
    monkeypatch.setitem(purge.HANDLERS, retention.AUDIT_LOGS, lambda *a, **k: (_ for _ in ()).throw(OSError("x")))
    assert purge_cli.main(["--policy", "audit_logs"]) == 1
    output = capsys.readouterr().out
    assert "failed after 1 attempt" in output and "purge_failed" in output


def test_cli_retries_failed_policies_and_succeeds_within_its_attempt_budget(session, monkeypatch, capsys):
    monkeypatch.setattr(purge_cli, "get_session_factory", lambda: lambda: session)
    sleeps: list[int] = []
    monkeypatch.setattr(purge_cli.time, "sleep", lambda seconds: sleeps.append(seconds))
    seen: list[int] = []
    real = purge.HANDLERS[retention.AUDIT_LOGS]

    def fail_first(sess, cutoff, result, settings, lease):
        seen.append(result.attempt)
        if result.attempt == 1:
            raise OSError("transient")
        return real(sess, cutoff, result, settings, lease)

    monkeypatch.setitem(purge.HANDLERS, retention.AUDIT_LOGS, fail_first)
    code = purge_cli.main(
        ["--policy", "audit_logs", "--policy", "raw_aggregates", "--max-attempts", "3", "--retry-delay-seconds", "5"]
    )
    assert code == 0
    assert seen == [1, 2] and sleeps == [5]
    output = capsys.readouterr().out
    assert "attempt 2" in output
    # Only the failed policy was retried.
    assert session.scalar(select(func.count()).where(MaintenanceRun.policy == retention.RAW_AGGREGATES)) == 1
    assert session.scalar(select(func.count()).where(MaintenanceRun.policy == retention.AUDIT_LOGS)) == 2


def test_a_locked_policy_is_not_a_failure(session, engine):
    from sqlalchemy.orm import sessionmaker

    other = sessionmaker(bind=engine, future=True)()
    try:
        assert purge.acquire_lease(other, "retention_purge:audit_logs", "other-holder", 600)
        results = purge.purge_expired(session, policy_names=[retention.AUDIT_LOGS])
        assert purge.raise_for_failures(results) == results
    finally:
        purge.release_lease(other, "retention_purge:audit_logs", "other-holder")
        other.close()


# ---------------------------------------------------------------------------
# Lease heartbeat and lease loss
# ---------------------------------------------------------------------------


def _old_audit_rows(session, count: int) -> None:
    session.add_all(
        AuditLog(action=f"old_{index}", resource_type="test", created_at=LONG_AGO - timedelta(days=400))
        for index in range(count)
    )
    session.commit()


def test_the_lease_is_renewed_in_every_batch(session, monkeypatch):
    _old_audit_rows(session, 3)
    monkeypatch.setattr(get_settings(), "purge_batch_size", 1)
    expiries: list[datetime] = []
    real = purge.renew_lease

    def spy(sess, name, holder, ttl, now=None):
        renewed = real(sess, name, holder, ttl, now)
        expiries.append(sess.get(MaintenanceLock, name).expires_at)
        return renewed

    monkeypatch.setattr(purge, "renew_lease", spy)
    result = purge_policy(session, retention.AUDIT_LOGS, dry_run=False)
    assert result.status == STATUS_COMPLETED and result.rows_deleted >= 3
    assert len(expiries) == result.batches


def test_a_purge_that_loses_its_lease_stops_before_the_next_batch(session, monkeypatch):
    _old_audit_rows(session, 4)
    before = session.scalar(select(func.count()).select_from(AuditLog))
    monkeypatch.setattr(get_settings(), "purge_batch_size", 1)
    calls = {"count": 0}
    real = purge.renew_lease

    def steal_on_second(sess, name, holder, ttl, now=None):
        calls["count"] += 1
        if calls["count"] == 2:
            sess.execute(
                update(MaintenanceLock)
                .where(MaintenanceLock.name == name)
                .values(holder="another-worker", expires_at=datetime.now(UTC) + timedelta(hours=1))
            )
            sess.commit()
        return real(sess, name, holder, ttl, now)

    monkeypatch.setattr(purge, "renew_lease", steal_on_second)
    result = purge_policy(session, retention.AUDIT_LOGS, dry_run=False)

    assert result.status == STATUS_FAILED and result.error_code == ERROR_LEASE_LOST
    assert result.rows_deleted == 1
    assert session.scalar(select(func.count()).select_from(AuditLog)) == before - 1
    # The new holder's lease is not released by the process that lost it.
    assert session.get(MaintenanceLock, "retention_purge:audit_logs").holder == "another-worker"


# ---------------------------------------------------------------------------
# Operational metadata retention
# ---------------------------------------------------------------------------


def test_operational_records_expire_after_their_window(session):
    stale, fresh = datetime.now(UTC) - timedelta(days=200), datetime.now(UTC)
    for moment in (stale, fresh):
        session.add(
            MaintenanceRun(
                task_type="retention_purge",
                policy="audit_logs",
                entity="audit_log",
                started_at=moment,
                status="completed",
                source="cli",
                created_at=moment,
            )
        )
        session.add(OperationalEvent(event_type="probe", created_at=moment))
    session.commit()
    result = purge_policy(session, retention.OPERATIONAL_RECORDS, dry_run=False)
    assert result.status == STATUS_COMPLETED and result.rows_deleted == 2
    assert session.scalar(select(func.count()).where(OperationalEvent.created_at < fresh - timedelta(days=1))) == 0
    assert session.scalar(select(func.count()).where(MaintenanceRun.created_at < fresh - timedelta(days=1))) == 0
    assert session.scalar(select(func.count()).select_from(OperationalEvent)) == 1

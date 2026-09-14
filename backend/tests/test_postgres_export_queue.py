"""PostgreSQL export queue: two-connection submission and claim races, durable failure, retries.

Runs only against the disposable verification cluster named by HPIP_POSTGRES_TEST_URL. The
database is created and dropped by the shared helpers and refuses to reuse an existing one.
"""

from __future__ import annotations

import threading
from threading import Barrier, Thread
from uuid import UUID

from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.db.session import reset_engine
from app.domain.enums import JobStatus
from app.main import app
from app.models import AuditLog, ExportJob, OrgUnit, User
from app.services import export_jobs, publishing
from app.services.seed import seed_reference_data
from tests.conftest import SEED_PASSWORD, auth_header, login, query_dashboard
from tests.helpers import put_population, put_raw
from tests.test_postgres_migrations import (
    _admin_url,
    _alembic_cfg,
    _cleanup,
    _point_alembic,
    _prepare_verify_db,
    requires_postgres,
)


def _independent_job(test_url: str, job_id: UUID) -> dict:
    """Read the committed row through a brand-new engine and connection."""
    engine = create_engine(test_url, future=True)
    try:
        with sessionmaker(bind=engine, future=True)() as session:
            job = session.get(ExportJob, job_id)
            return {
                "status": job.status,
                "error_code": job.error_code,
                "attempt_count": job.attempt_count,
                "retry_scheduled": job.retry_scheduled,
                "active_key": job.active_key,
                "file_path": job.file_path,
                "checksum": job.checksum,
            }
    finally:
        engine.dispose()


@requires_postgres
def test_postgres_export_queue_races_and_durable_failure(monkeypatch, tmp_path):
    admin, test_url = _prepare_verify_db(_admin_url())
    _point_alembic(monkeypatch, test_url)
    engine = None
    try:
        command.upgrade(_alembic_cfg(), "head")
        monkeypatch.setenv("EXPORT_DIR", str(tmp_path / "artifacts"))
        monkeypatch.setenv("EXPORT_EAGER", "false")
        get_settings.cache_clear()
        reset_engine()
        engine = create_engine(test_url, future=True)
        factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
        with factory() as setup:
            seed_reference_data(setup, SEED_PASSWORD)
            pader = setup.scalar(select(OrgUnit).where(OrgUnit.code == "PADER"))
            put_population(setup, pader, 2024, 1_000_000, code="PG_QUEUE_POP")
            put_raw(setup, pader, "FY2024/25", "ANC1", 40_000)
            setup.commit()
            pader_id = pader.id
        app.dependency_overrides.clear()
        with TestClient(app) as client:
            headers = auth_header(login(client, "pader.focal"))
            dash = query_dashboard(client, headers, pader_id)
            assert dash.status_code == 201, dash.text
            snapshot = dash.json()

        # 1. Two connections submit the same export at the same time: one job, one creator.
        barrier = Barrier(2)
        local = threading.local()
        real_lookup = export_jobs._live_job

        def racing_lookup(session, key):
            first = not getattr(local, "seen", False)
            local.seen = True
            found = real_lookup(session, key)
            if first:
                barrier.wait(timeout=15)
            return found

        monkeypatch.setattr(export_jobs, "_live_job", racing_lookup)
        outcomes: list[tuple[str, bool]] = []
        errors: list[BaseException] = []

        def _submit_powerpoint() -> None:
            session = factory()
            try:
                user = session.scalar(select(User).where(User.username == "pader.focal"))
                submission = export_jobs.submit_export(
                    session,
                    user=user,
                    export_type="powerpoint",
                    org_unit_id=pader_id,
                    period="FY2024/25",
                    module="anc",
                    analysis_snapshot_id=UUID(snapshot["analysis_snapshot_id"]),
                    view_hash=snapshot["view_hash"],
                )
                job_id = str(submission.job.id)
                session.commit()
                outcomes.append((job_id, submission.created))
            except BaseException as exc:  # noqa: BLE001
                session.rollback()
                errors.append(exc)
            finally:
                session.close()

        threads = [Thread(target=_submit_powerpoint) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
        monkeypatch.setattr(export_jobs, "_live_job", real_lookup)
        assert errors == []
        assert len(outcomes) == 2
        assert len({job_id for job_id, _created in outcomes}) == 1
        assert sorted(created for _job_id, created in outcomes) == [False, True]
        job_id = UUID(outcomes[0][0])
        with factory() as check:
            key = check.get(ExportJob, job_id).active_key
            assert len(key) == 84  # user uuid + snapshot uuid + "powerpoint" exceeded the old VARCHAR(80)
            same_key = select(func.count()).select_from(ExportJob).where(ExportJob.idempotency_key == key)
            assert check.scalar(same_key) == 1

        # 2. Two workers claim the same job concurrently: exactly one wins.
        claim_barrier = Barrier(2)
        claims: list[bool] = []

        def _claim(token: str) -> None:
            session = factory()
            try:
                claim_barrier.wait(timeout=15)
                claims.append(export_jobs._claim(session, job_id, token))
            finally:
                session.close()

        claimers = [Thread(target=_claim, args=(f"token-{index}",)) for index in range(2)]
        for thread in claimers:
            thread.start()
        for thread in claimers:
            thread.join(timeout=60)
        assert sorted(claims) == [False, True]
        with factory() as reset:
            job = reset.get(ExportJob, job_id)
            job.status = JobStatus.QUEUED.value
            job.claim_token = None
            job.attempt_count = 0
            reset.commit()

        # 3. A failing worker attempt is rolled back and committed as failed in a clean transaction.
        def broken(_dashboard, _package, destination):
            raise OSError(f"disk failure at {destination}")

        monkeypatch.setitem(publishing.ARTIFACT_WRITERS, "powerpoint", broken)
        first = export_jobs.process_export_job(job_id, factory=factory, auto_retry=True)
        assert first.outcome == "retry"
        seen = _independent_job(test_url, job_id)
        assert seen["status"] == JobStatus.FAILED.value
        assert seen["error_code"] == export_jobs.GENERATION_FAILED
        assert seen["retry_scheduled"] is True and seen["attempt_count"] == 1 and seen["active_key"]

        # 4. Publication failure after the success UPDATE rolls back the UPDATE and its audit row.
        monkeypatch.setitem(publishing.ARTIFACT_WRITERS, "powerpoint", publishing._write_pptx)

        def replace_fails(_src, _dst):
            raise PermissionError("cannot publish")

        with monkeypatch.context() as patch:
            patch.setattr(export_jobs.os, "replace", replace_fails)
            second = export_jobs.process_export_job(job_id, factory=factory, auto_retry=True)
        assert second.outcome == "retry"
        seen = _independent_job(test_url, job_id)
        assert seen["status"] == JobStatus.FAILED.value and seen["file_path"] is None and seen["checksum"] is None

        # 5. The retry succeeds: failed -> running -> succeeded on the third bounded attempt.
        third = export_jobs.process_export_job(job_id, factory=factory, auto_retry=True)
        assert third.outcome == "succeeded"
        seen = _independent_job(test_url, job_id)
        assert seen["status"] == JobStatus.SUCCEEDED.value and seen["attempt_count"] == 3 and seen["checksum"]
        with factory() as check:
            actions = check.scalars(select(AuditLog.action).where(AuditLog.resource_id == str(job_id))).all()
        assert actions.count("export_generated") == 1
        assert actions.count("export_failed") == 2

        # 6. Permanent failure releases the live key and a new submission creates a new job.
        with TestClient(app) as client:
            headers = auth_header(login(client, "pader.focal"))
            body = {
                "org_unit_id": str(pader_id),
                "period": "FY2024/25",
                "module": "anc",
                "analysis_snapshot_id": snapshot["analysis_snapshot_id"],
                "view_hash": snapshot["view_hash"],
            }
            created = client.post("/exports/report", json=body, headers=headers)
            assert created.status_code == 202, created.text
            report_id = UUID(created.json()["job_id"])
            monkeypatch.setitem(publishing.ARTIFACT_WRITERS, "report", broken)
            attempts = [export_jobs.process_export_job(report_id, factory=factory) for _ in range(3)]
            assert [item.outcome for item in attempts] == ["retry", "retry", "failed"]
            seen = _independent_job(test_url, report_id)
            assert seen["active_key"] is None and seen["retry_scheduled"] is False
            monkeypatch.setitem(publishing.ARTIFACT_WRITERS, "report", publishing._write_report)
            again = client.post("/exports/report", json=body, headers=headers)
            assert again.status_code == 202, again.text
            assert UUID(again.json()["job_id"]) != report_id
            history = client.get("/exports/jobs", headers=headers).json()["jobs"]
        assert str(report_id) in {row["job_id"] for row in history}
    finally:
        if engine is not None:
            engine.dispose()
        _cleanup(admin, monkeypatch)

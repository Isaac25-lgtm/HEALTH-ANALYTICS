"""True two-connection PostgreSQL tests. Never reuse the shared SQLite session fixture."""

from __future__ import annotations

from threading import Barrier, Thread

from alembic import command
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models import FacilityPopulationEntry, OrgUnit, User
from app.services.population import approve_facility_population, enter_facility_population
from app.services.seed import seed_reference_data
from tests.conftest import SEED_PASSWORD
from tests.test_postgres_migrations import (
    VERIFY_DB,
    _admin_url,
    _alembic_cfg,
    _cleanup,
    _point_alembic,
    _prepare_verify_db,
    requires_postgres,
)


@requires_postgres
def test_postgres_two_connection_facility_population_approval(monkeypatch):
    admin, test_url = _prepare_verify_db(_admin_url())
    _point_alembic(monkeypatch, test_url)
    try:
        command.upgrade(_alembic_cfg(), "head")
        engine = create_engine(test_url, future=True)
        factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
        setup = factory()
        seed_reference_data(setup, SEED_PASSWORD)
        facility = setup.scalar(select(OrgUnit).where(OrgUnit.code == "PADER_HC_III"))
        editor = setup.scalar(select(User).where(User.username == "pader.focal"))
        first = enter_facility_population(
            setup,
            editor,
            org_unit_id=facility.id,
            year=2024,
            population=1200,
            source_name="Synthetic concurrency A",
            population_type="facility_catchment_estimate",
            reason="Two-connection approval race A",
        )
        second = enter_facility_population(
            setup,
            editor,
            org_unit_id=facility.id,
            year=2024,
            population=1300,
            source_name="Synthetic concurrency B",
            population_type="facility_catchment_estimate",
            reason="Two-connection approval race B",
        )
        first_id, second_id = first.id, second.id
        facility_id = facility.id
        setup.commit()
        setup.close()

        barrier = Barrier(2)
        outcomes: list[str] = []

        def _approve(entry_id) -> None:
            session = factory()
            try:
                approver = session.scalar(select(User).where(User.username == "admin.user"))
                barrier.wait(timeout=10)
                approve_facility_population(session, approver, entry_id, reason="concurrent two-connection test")
                session.commit()
                outcomes.append("committed")
            except Exception:
                session.rollback()
                outcomes.append("rejected")
            finally:
                session.close()

        workers = [
            Thread(target=_approve, args=(first_id,)),
            Thread(target=_approve, args=(second_id,)),
        ]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=30)

        verify = factory()
        current = verify.scalars(
            select(FacilityPopulationEntry).where(
                FacilityPopulationEntry.org_unit_id == facility_id,
                FacilityPopulationEntry.year == 2024,
                FacilityPopulationEntry.is_current_approved.is_(True),
            )
        ).all()
        verify.close()
        engine.dispose()
        assert len(current) == 1
        assert outcomes.count("committed") >= 1
    finally:
        _cleanup(admin, monkeypatch)


@requires_postgres
def test_postgres_verify_database_name_is_exact(monkeypatch):
    assert VERIFY_DB == "hpip_p18_alembic_verify"
    admin, test_url = _prepare_verify_db(_admin_url())
    assert test_url.rstrip("/").endswith(VERIFY_DB)
    _cleanup(admin, monkeypatch)


@requires_postgres
def test_postgres_two_user_facility_queue_race(monkeypatch):
    """Both service calls race, not merely two direct INSERTs into the unique index."""
    from app.models import Programme, SyncJob
    from app.services import facility_data
    from tests.helpers import map_source

    admin, test_url = _prepare_verify_db(_admin_url())
    _point_alembic(monkeypatch, test_url)
    try:
        command.upgrade(_alembic_cfg(), "head")
        engine = create_engine(test_url, future=True)
        factory = sessionmaker(bind=engine, autoflush=False, future=True)
        with factory() as setup:
            seed_reference_data(setup, SEED_PASSWORD)
            district_id = setup.scalar(select(OrgUnit.id).where(OrgUnit.code == "PADER"))
            users = list(setup.scalars(select(User.id).where(User.username.in_(("admin.user", "pader.focal")))))
            programme = setup.scalar(select(Programme).where(Programme.code == "MNCH"))
            map_source(setup, programme.id, "ANC1", "TEST_ONLY_RACE_ANC1")
            setup.commit()
        monkeypatch.setattr(facility_data, "ensure_extraction_enabled", lambda _settings: None)
        barrier = Barrier(2)
        outcomes, errors = [], []

        def queue(user_id):
            with factory() as db:
                try:
                    user, district = db.get(User, user_id), db.get(OrgUnit, district_id)
                    barrier.wait(timeout=10)
                    status = facility_data.queue_facility_load(
                        db, user=user, org_unit=district, period="FY2024/25", module="anc"
                    )
                    db.commit()
                    outcomes.append(status.job_id)
                except Exception as exc:
                    db.rollback()
                    errors.append(type(exc).__name__)

        threads = [Thread(target=queue, args=(user_id,)) for user_id in users]
        assert len(threads) == 2
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)
        assert not any(thread.is_alive() for thread in threads)
        assert errors == [] and len(outcomes) == 2 and len(set(outcomes)) == 1
        with factory() as verify:
            active = list(verify.scalars(select(SyncJob).where(SyncJob.status.in_(("queued", "running")))))
            assert len(active) == 1 and str(active[0].id) == outcomes[0]
        engine.dispose()
    finally:
        _cleanup(admin, monkeypatch)


@requires_postgres
def test_postgres_two_connection_dispatch_recovery_claim(monkeypatch):
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace

    from app.models import SyncJob
    from app.services import sync_recovery

    admin, test_url = _prepare_verify_db(_admin_url())
    _point_alembic(monkeypatch, test_url)
    try:
        command.upgrade(_alembic_cfg(), "head")
        engine = create_engine(test_url, future=True)
        factory = sessionmaker(bind=engine, autoflush=False, future=True)
        now = datetime.now(UTC)
        with factory() as setup:
            job = SyncJob(job_type="aggregate", status="queued", updated_at=now - timedelta(minutes=5))
            setup.add(job)
            setup.flush()
            job_id = job.id
            setup.commit()
        monkeypatch.setattr(
            sync_recovery, "get_settings", lambda: SimpleNamespace(dhis2_enabled=True, sync_enabled=True)
        )
        monkeypatch.setattr(sync_recovery, "should_run_eager", lambda: False)
        barrier = Barrier(2)
        delivered, results, errors = [], [], []

        def recover():
            with factory() as db:
                try:
                    barrier.wait(timeout=10)
                    results.append(sync_recovery.recover_sync_dispatch(db, now=now, dispatch=delivered.append))
                except Exception as exc:
                    db.rollback()
                    errors.append(type(exc).__name__)

        threads = [Thread(target=recover), Thread(target=recover)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)
        assert not any(thread.is_alive() for thread in threads)
        assert errors == [] and len(results) == 2
        assert sum(result["published"] for result in results) == 1 and delivered == [job_id]
        engine.dispose()
    finally:
        _cleanup(admin, monkeypatch)

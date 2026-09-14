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

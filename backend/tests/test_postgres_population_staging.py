"""PostgreSQL: concurrent population staging reuses one governed batch; migration 0012 round-trips.

Runs only against the disposable verification cluster named by HPIP_POSTGRES_TEST_URL. The
database is created and dropped by the shared helpers and refuses to reuse an existing one.
"""

from __future__ import annotations

import warnings
from threading import Barrier, Thread

from alembic import command
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.orm import sessionmaker

from app.models import PopulationImportBatch, PopulationImportRow, User, UserPermission
from app.services.population_workbook import (
    file_sha256,
    read_population_workbook,
    reconcile_workbook,
    stage_population_workbook,
)
from app.services.seed import seed_reference_data
from tests.conftest import SEED_PASSWORD
from tests.test_population_workbook import SYNTHETIC, _write_workbook
from tests.test_postgres_migrations import (
    HEAD_REVISION,
    _admin_url,
    _alembic_cfg,
    _cleanup,
    _point_alembic,
    _prepare_verify_db,
    requires_postgres,
)


@requires_postgres
def test_postgres_concurrent_staging_creates_one_batch(monkeypatch, tmp_path):
    admin, test_url = _prepare_verify_db(_admin_url())
    _point_alembic(monkeypatch, test_url)
    try:
        command.upgrade(_alembic_cfg(), "head")
        engine = create_engine(test_url, future=True, pool_size=6)
        factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
        with factory() as setup:
            seed_reference_data(setup, SEED_PASSWORD)
            user = setup.scalar(select(User).where(User.username == "pader.focal"))
            setup.add(UserPermission(user_id=user.id, action="edit_population"))
            setup.commit()
            user_id = user.id
        path = tmp_path / "concurrent.xlsx"
        _write_workbook(path, SYNTHETIC)
        sha = file_sha256(path)
        workers = 4
        barrier = Barrier(workers)
        outcomes: list[tuple[str, bool]] = []
        errors: list[BaseException] = []

        def stage() -> None:
            with factory() as session:
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        extract = read_population_workbook(path, expected_sha256=sha)
                    report = reconcile_workbook(session, extract)
                    importer = session.get(User, user_id)
                    barrier.wait(timeout=30)
                    outcome = stage_population_workbook(session, importer, report=report)
                    session.commit()
                    outcomes.append((str(outcome.batch.id), outcome.reused))
                except BaseException as exc:  # surfaced below
                    session.rollback()
                    errors.append(exc)

        threads = [Thread(target=stage) for _ in range(workers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=120)
        assert not errors, errors
        assert len({batch_id for batch_id, _reused in outcomes}) == 1, outcomes
        assert sorted(reused for _batch_id, reused in outcomes) == [False] + [True] * (workers - 1)
        with factory() as check:
            assert check.scalar(select(func.count()).select_from(PopulationImportBatch)) == 1
            assert check.scalar(select(func.count()).select_from(PopulationImportRow)) == len(SYNTHETIC) * 7
        engine.dispose()
    finally:
        _cleanup(admin, monkeypatch)


@requires_postgres
def test_postgres_0011_to_0012_adds_the_staging_identity_and_downgrades(monkeypatch):
    admin, test_url = _prepare_verify_db(_admin_url())
    _point_alembic(monkeypatch, test_url)
    try:
        cfg = _alembic_cfg()
        command.upgrade(cfg, "0011_population_import_staging")
        command.upgrade(cfg, "0012_population_staging_identity")
        engine = create_engine(test_url, future=True)
        columns = {column["name"] for column in inspect(engine).get_columns("population_import_batches")}
        indexes = {index["name"]: index for index in inspect(engine).get_indexes("population_import_batches")}
        engine.dispose()
        assert "reference_fingerprint" in columns
        assert indexes["uq_population_import_batches_identity"]["unique"]
        command.downgrade(cfg, "0011_population_import_staging")
        engine = create_engine(test_url, future=True)
        columns = {column["name"] for column in inspect(engine).get_columns("population_import_batches")}
        engine.dispose()
        assert "reference_fingerprint" not in columns
        command.upgrade(cfg, "head")
        engine = create_engine(test_url, future=True)
        with engine.connect() as conn:
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == HEAD_REVISION
        engine.dispose()
    finally:
        _cleanup(admin, monkeypatch)

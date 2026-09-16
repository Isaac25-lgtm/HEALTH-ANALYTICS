"""PostgreSQL: fresh release flow and concurrent reference bootstraps.

Runs only against the disposable verification cluster named by HPIP_POSTGRES_TEST_URL. The
database is created and dropped by the shared helpers and refuses to reuse an existing one.
"""

from __future__ import annotations

from threading import Barrier, Thread

import pytest
from alembic import command
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.models import OrgUnit, PeriodPopulationRule
from app.services.reference_bootstrap import ReferenceBootstrapConflict, bootstrap_reference_data
from tests.test_postgres_migrations import (
    _admin_url,
    _alembic_cfg,
    _cleanup,
    _point_alembic,
    _prepare_verify_db,
    requires_postgres,
)
from tests.test_reference_bootstrap import expected_reference_counts, reference_counts, run_release


@requires_postgres
def test_postgres_fresh_release_bootstrap_admin_and_login(monkeypatch, capsys):
    admin, test_url = _prepare_verify_db(_admin_url())
    try:
        run_release(monkeypatch, test_url, capsys)
    finally:
        _cleanup(admin, monkeypatch)


@requires_postgres
def test_postgres_concurrent_release_bootstraps_create_no_duplicates(monkeypatch):
    admin, test_url = _prepare_verify_db(_admin_url())
    _point_alembic(monkeypatch, test_url)
    try:
        command.upgrade(_alembic_cfg(), "head")
        workers = 5
        engine = create_engine(test_url, future=True, pool_size=workers)
        factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
        barrier = Barrier(workers)
        created: list[bool] = []
        errors: list[BaseException] = []

        def release() -> None:
            with factory() as session:
                try:
                    barrier.wait(timeout=30)
                    report = bootstrap_reference_data(session)
                    session.commit()
                    created.append(report.changed)
                except BaseException as exc:  # surfaced below
                    session.rollback()
                    errors.append(exc)

        threads = [Thread(target=release) for _ in range(workers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=120)
        assert not errors, errors
        # Exactly one release created the reference; the others waited on the advisory lock and
        # found everything present.
        assert sorted(created) == [False] * (workers - 1) + [True]
        with factory() as session:
            assert reference_counts(session) == expected_reference_counts()
            # NULL programme_id is not covered by the unique constraint, so duplicates would only
            # be prevented by the lock.
            duplicates = session.execute(
                select(PeriodPopulationRule.financial_year_key, func.count())
                .where(PeriodPopulationRule.programme_id.is_(None))
                .group_by(PeriodPopulationRule.financial_year_key)
                .having(func.count() > 1)
            ).all()
            assert duplicates == []
        engine.dispose()
    finally:
        _cleanup(admin, monkeypatch)


@requires_postgres
def test_postgres_every_bootstrap_owned_field_drift_is_refused(monkeypatch, capsys):
    from scripts import bootstrap_reference_data as bootstrap_cli
    from tests import reference_mutations
    from tests.test_reference_bootstrap import point_at

    admin, test_url = _prepare_verify_db(_admin_url())
    try:
        point_at(monkeypatch, test_url)
        command.upgrade(_alembic_cfg(), "head")
        assert bootstrap_cli.main([]) == 0
        engine = create_engine(test_url, future=True)
        missing = reference_mutations.remove_one_missing_row(engine)
        refused: list[str] = []
        for mutation_id in reference_mutations.ALL_IDS:
            undo = reference_mutations.apply(engine, mutation_id)
            capsys.readouterr()
            code = bootstrap_cli.main([])
            output = capsys.readouterr().out
            assert code == 3, (mutation_id, output)
            assert reference_mutations.expected_fragment(mutation_id) in output, (mutation_id, output)
            assert reference_mutations.SENTINEL not in output, mutation_id
            assert missing() == 0, mutation_id
            undo()
            refused.append(mutation_id)
        assert refused == reference_mutations.ALL_IDS
        assert bootstrap_cli.main([]) == 0
        assert missing() == 1
        with sessionmaker(bind=engine, future=True)() as session:
            assert reference_counts(session) == expected_reference_counts()
        engine.dispose()
    finally:
        _cleanup(admin, monkeypatch)


@requires_postgres
def test_postgres_bootstrap_rejects_another_active_country_root(monkeypatch):
    admin, test_url = _prepare_verify_db(_admin_url())
    _point_alembic(monkeypatch, test_url)
    try:
        command.upgrade(_alembic_cfg(), "head")
        engine = create_engine(test_url, future=True)
        with sessionmaker(bind=engine, future=True)() as session:
            bootstrap_reference_data(session)
            session.commit()
            session.add(
                OrgUnit(
                    code="OTHER_COUNTRY",
                    name="Another active country",
                    level_type="country",
                    parent_id=None,
                    path="/OTHER_COUNTRY",
                    active=True,
                )
            )
            session.commit()
            with pytest.raises(ReferenceBootstrapConflict):
                bootstrap_reference_data(session)
            session.rollback()
        engine.dispose()
    finally:
        _cleanup(admin, monkeypatch)

"""PostgreSQL retention: the 0009 artifact backfill and downgrade, and purge leases under real contention.

Runs only against the disposable verification cluster named by HPIP_POSTGRES_TEST_URL. The
database is created and dropped by the shared helpers and refuses to reuse an existing one.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from threading import Barrier, Thread

from alembic import command
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from app.models import MaintenanceLock
from app.services import purge
from tests.test_postgres_migrations import (
    HEAD_REVISION,
    _admin_url,
    _alembic_cfg,
    _cleanup,
    _legacy_export_rows,
    _point_alembic,
    _prepare_verify_db,
    requires_postgres,
)


@requires_postgres
def test_postgres_0008_to_0009_backfills_artifact_expiry_and_downgrades(monkeypatch):
    admin, test_url = _prepare_verify_db(_admin_url())
    _point_alembic(monkeypatch, test_url)
    try:
        cfg = _alembic_cfg()
        command.upgrade(cfg, "0007_amendment_corrections")
        engine = create_engine(test_url, future=True)
        legacy = _legacy_export_rows(engine)
        engine.dispose()
        command.upgrade(cfg, "0008_export_queue_durability")
        finished = datetime(2026, 2, 1, 8, 30, tzinfo=UTC)
        engine = create_engine(test_url, future=True)
        with engine.begin() as conn:
            # Succeeded with a file and a finish time: expiry is finish + 24 h.
            conn.execute(
                text("UPDATE export_jobs SET file_path = 'a.xlsx', finished_at = :f WHERE id = :id"),
                {"f": finished, "id": legacy["newer"]},
            )
            # Succeeded with a file but no finish time: expiry falls back to creation + 24 h.
            conn.execute(text("UPDATE export_jobs SET file_path = 'b.xlsx' WHERE id = :id"), {"id": legacy["older"]})
            # Failed jobs are not artifacts, even with a stray path.
            conn.execute(text("UPDATE export_jobs SET file_path = 'c.xlsx' WHERE id = :id"), {"id": legacy["failed"]})
        engine.dispose()

        command.upgrade(cfg, "0009_retention_artifacts")
        engine = create_engine(test_url, future=True)
        with engine.connect() as conn:
            rows = {
                row[0]: row
                for row in conn.execute(
                    text("SELECT id, artifact_storage, artifact_expires_at, artifact_deleted_at FROM export_jobs")
                ).all()
            }
        tables = set(inspect(engine).get_table_names())
        engine.dispose()
        assert {"export_artifacts", "maintenance_runs", "maintenance_locks"} <= tables
        assert rows[legacy["newer"]][1] == "filesystem"
        assert rows[legacy["newer"]][2] == finished + timedelta(hours=24)
        assert rows[legacy["older"]][1] == "filesystem"
        assert rows[legacy["older"]][2] == datetime(2026, 1, 2, tzinfo=UTC)
        assert rows[legacy["failed"]][2] is None
        assert rows[legacy["queued"]][2] is None
        assert all(row[3] is None for row in rows.values())

        command.downgrade(cfg, "0008_export_queue_durability")
        engine = create_engine(test_url, future=True)
        tables = set(inspect(engine).get_table_names())
        columns = {column["name"] for column in inspect(engine).get_columns("export_jobs")}
        with engine.connect() as conn:
            surviving = conn.execute(text("SELECT count(*) FROM export_jobs")).scalar_one()
        engine.dispose()
        assert not {"export_artifacts", "maintenance_runs", "maintenance_locks"} & tables
        assert "artifact_expires_at" not in columns and "artifact_storage" not in columns
        assert surviving == 4

        command.upgrade(cfg, "head")
        engine = create_engine(test_url, future=True)
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        columns = {column["name"] for column in inspect(engine).get_columns("calculated_values")}
        tables = set(inspect(engine).get_table_names())
        engine.dispose()
        assert version == HEAD_REVISION
        assert "denominator_provenance" in columns
        assert {"population_import_batches", "population_import_rows"} <= tables
    finally:
        _cleanup(admin, monkeypatch)


def _race(test_url: str, name: str, holders: list[str], now: datetime) -> dict[str, bool]:
    engine = create_engine(test_url, future=True, pool_size=len(holders))
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    barrier = Barrier(len(holders))
    outcome: dict[str, bool] = {}
    errors: list[BaseException] = []

    def attempt(holder: str) -> None:
        with factory() as session:
            try:
                barrier.wait(timeout=30)
                outcome[holder] = purge.acquire_lease(session, name, holder, 600, now=now)
            except BaseException as exc:  # surfaced below; a thread must not swallow it
                errors.append(exc)

    threads = [Thread(target=attempt, args=(holder,)) for holder in holders]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    engine.dispose()
    assert not errors, errors
    return outcome


@requires_postgres
def test_postgres_purge_lease_admits_exactly_one_holder_under_contention(monkeypatch):
    admin, test_url = _prepare_verify_db(_admin_url())
    _point_alembic(monkeypatch, test_url)
    try:
        command.upgrade(_alembic_cfg(), "head")
        holders = [f"worker-{index}" for index in range(6)]
        now = datetime.now(UTC)

        # A fresh lease: concurrent inserts race on the primary key; one wins.
        fresh = _race(test_url, "retention_purge:audit_logs", holders, now)
        assert sorted(fresh.values()) == [False] * 5 + [True]

        # A stale lease: concurrent conditional UPDATEs race; the row lock admits one taker.
        engine = create_engine(test_url, future=True)
        factory = sessionmaker(bind=engine, future=True)
        stale = now - timedelta(hours=2)
        with factory() as session:
            session.add(
                MaintenanceLock(name="retention_purge:raw", holder="dead-worker", acquired_at=stale, expires_at=stale)
            )
            session.commit()
        taken = _race(test_url, "retention_purge:raw", holders, now)
        assert sorted(taken.values()) == [False] * 5 + [True]
        winner = next(holder for holder, won in taken.items() if won)
        with factory() as session:
            lock = session.get(MaintenanceLock, "retention_purge:raw")
            assert lock.holder == winner
            # Only the holder can release it.
            purge.release_lease(session, "retention_purge:raw", "someone-else")
            assert session.get(MaintenanceLock, "retention_purge:raw") is not None
            purge.release_lease(session, "retention_purge:raw", winner)
            session.expire_all()
            assert session.get(MaintenanceLock, "retention_purge:raw") is None
        engine.dispose()
    finally:
        _cleanup(admin, monkeypatch)

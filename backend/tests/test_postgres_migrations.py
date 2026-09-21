import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from historical.phase1 import PHASE1_TABLES
from historical.phase2 import PHASE2_TABLES
from sqlalchemy import MetaData, create_engine, inspect, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import reset_engine
from app.services.sync import sync_job_execution_lock

# No default server: PostgreSQL tests run only against the disposable cluster named explicitly by
# HPIP_POSTGRES_TEST_URL, so the suite never attempts to log in to a workstation instance.
DEFAULT_ADMIN_URL = ""
VERIFY_DB = "hpip_p18_alembic_verify"
HEAD_REVISION = "0013_org_mapping_guard"


def _admin_url() -> str:
    return os.environ.get("HPIP_POSTGRES_TEST_URL", DEFAULT_ADMIN_URL)


def _connect_args(url: str) -> dict:
    if url.startswith("postgresql"):
        return {"connect_timeout": 5}
    return {}


def _can_connect(url: str) -> bool:
    if not url:
        return False
    try:
        engine = create_engine(url, future=True, connect_args=_connect_args(url))
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


postgres_available = _can_connect(_admin_url())
requires_postgres = pytest.mark.skipif(
    not postgres_available,
    reason="PostgreSQL is not available (set HPIP_POSTGRES_TEST_URL to a disposable cluster)",
)


def _alembic_cfg() -> Config:
    return Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))


def _prepare_verify_db(admin_url: str) -> tuple:
    admin = create_engine(admin_url, future=True)
    with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :name"),
            {"name": VERIFY_DB},
        ).scalar()
        if exists:
            raise RuntimeError(
                f"Refusing to create {VERIFY_DB}: the disposable verification database already exists."
            )
        conn.execute(text(f"CREATE DATABASE {VERIFY_DB}"))
    test_url = admin_url.rsplit("/", 1)[0] + f"/{VERIFY_DB}"
    return admin, test_url


def _cleanup(admin, monkeypatch) -> None:
    with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                f"WHERE datname = '{VERIFY_DB}' AND pid <> pg_backend_pid()"
            )
        )
        conn.execute(text(f"DROP DATABASE IF EXISTS {VERIFY_DB}"))
    admin.dispose()
    get_settings.cache_clear()
    reset_engine()
    monkeypatch.delenv("DATABASE_URL", raising=False)


def _point_alembic(monkeypatch, test_url: str) -> None:
    monkeypatch.setenv("DATABASE_URL", test_url)
    get_settings.cache_clear()
    reset_engine()


@requires_postgres
def test_postgres_upgrade_empty_database_to_head(monkeypatch):
    admin, test_url = _prepare_verify_db(_admin_url())
    _point_alembic(monkeypatch, test_url)
    try:
        command.upgrade(_alembic_cfg(), "head")
        engine = create_engine(test_url, future=True)
        names = set(inspect(engine).get_table_names())
        export_cols = {column["name"] for column in inspect(engine).get_columns("export_jobs")}
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            overlap_guard = conn.execute(
                text(
                    "SELECT 1 FROM pg_constraint "
                    "WHERE conname = 'ex_org_mapping_no_overlap' AND contype = 'x'"
                )
            ).scalar()
        first_unit, second_unit = str(uuid4()), str(uuid4())
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO org_units "
                    "(id, code, name, level_type, path, active) VALUES "
                    "(:first, 'OVERLAP_A', 'Overlap A', 'district', '/UG/OVERLAP_A', true), "
                    "(:second, 'OVERLAP_B', 'Overlap B', 'district', '/UG/OVERLAP_B', true)"
                ),
                {"first": first_unit, "second": second_unit},
            )
        first = engine.connect()
        second = engine.connect()
        first_tx = first.begin()
        second_tx = second.begin()
        try:
            first.execute(
                text(
                    "INSERT INTO org_unit_mappings "
                    "(id, org_unit_id, source_system, external_uid, valid_from, valid_to) "
                    "VALUES (:id, :unit, 'dhis2', 'Abcdef12345', '2026-01-01', '2026-12-31')"
                ),
                {"id": str(uuid4()), "unit": first_unit},
            )
            second.execute(text("SET LOCAL lock_timeout = '250ms'"))
            with pytest.raises(DBAPIError):
                second.execute(
                    text(
                        "INSERT INTO org_unit_mappings "
                        "(id, org_unit_id, source_system, external_uid, valid_from, valid_to) "
                        "VALUES (:id, :unit, 'dhis2', 'Abcdef12345', "
                        "'2026-06-01', '2027-05-31')"
                    ),
                    {"id": str(uuid4()), "unit": second_unit},
                )
            second_tx.rollback()
            first_tx.commit()
        finally:
            if first_tx.is_active:
                first_tx.rollback()
            if second_tx.is_active:
                second_tx.rollback()
            first.close()
            second.close()
        with engine.connect() as conn:
            transaction = conn.begin()
            with pytest.raises(IntegrityError):
                conn.execute(
                    text(
                        "INSERT INTO org_unit_mappings "
                        "(id, org_unit_id, source_system, external_uid, valid_from, valid_to) "
                        "VALUES (:id, :unit, 'dhis2', 'Abcdef12345', "
                        "'2026-06-01', '2027-05-31')"
                    ),
                    {"id": str(uuid4()), "unit": second_unit},
                )
            transaction.rollback()
        lock_id = uuid4()
        with Session(engine) as first_session, Session(engine) as second_session:
            with sync_job_execution_lock(first_session, lock_id) as first_acquired:
                assert first_acquired is True
                with sync_job_execution_lock(second_session, lock_id) as duplicate_acquired:
                    assert duplicate_acquired is False
            with sync_job_execution_lock(second_session, lock_id) as reclaimed_after_release:
                assert reclaimed_after_release is True
        engine.dispose()
        assert version == HEAD_REVISION
        assert "users" in names
        assert "sync_jobs" in names
        assert "auth_sessions" in names
        assert "alembic_version" in names
        assert "file_path" in export_cols
        assert overlap_guard == 1
    finally:
        _cleanup(admin, monkeypatch)


@requires_postgres
def test_postgres_revision_0001_creates_only_phase1_tables(monkeypatch):
    admin, test_url = _prepare_verify_db(_admin_url())
    _point_alembic(monkeypatch, test_url)
    try:
        command.upgrade(_alembic_cfg(), "0001_phase1_foundation")
        engine = create_engine(test_url, future=True)
        names = set(inspect(engine).get_table_names()) - {"alembic_version"}
        engine.dispose()
        assert names == set(PHASE1_TABLES)
        assert not (set(PHASE2_TABLES) & names)
        assert "auth_sessions" not in names
    finally:
        _cleanup(admin, monkeypatch)


@requires_postgres
def test_postgres_revision_0001_to_0002_creates_phase2_delta(monkeypatch):
    admin, test_url = _prepare_verify_db(_admin_url())
    _point_alembic(monkeypatch, test_url)
    try:
        cfg = _alembic_cfg()
        command.upgrade(cfg, "0001_phase1_foundation")
        command.upgrade(cfg, "0002_phase2_engines")
        engine = create_engine(test_url, future=True)
        names = set(inspect(engine).get_table_names())
        engine.dispose()
        assert set(PHASE2_TABLES) <= names
        assert "auth_sessions" not in names
    finally:
        _cleanup(admin, monkeypatch)


@requires_postgres
def test_postgres_upgrade_previous_head_to_audit_fix_head(monkeypatch):
    admin, test_url = _prepare_verify_db(_admin_url())
    _point_alembic(monkeypatch, test_url)
    try:
        cfg = _alembic_cfg()
        command.upgrade(cfg, "0003_phase12_corrections")
        command.upgrade(cfg, "0004_phase12_audit_fixes")
        engine = create_engine(test_url, future=True)
        names = set(inspect(engine).get_table_names())
        columns = {column["name"] for column in inspect(engine).get_columns("raw_aggregate_values")}
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        engine.dispose()
        assert version == "0004_phase12_audit_fixes"
        assert "auth_sessions" in names
        assert "login_attempts" in names
        assert "programme_id" in columns
    finally:
        _cleanup(admin, monkeypatch)


@requires_postgres
def test_postgres_downgrade_is_explicit(monkeypatch):
    admin, test_url = _prepare_verify_db(_admin_url())
    _point_alembic(monkeypatch, test_url)
    try:
        cfg = _alembic_cfg()
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "0002_phase2_engines")
        engine = create_engine(test_url, future=True)
        names = set(inspect(engine).get_table_names())
        engine.dispose()
        assert "auth_sessions" not in names
        assert "sync_jobs" in names
        command.downgrade(cfg, "0001_phase1_foundation")
        engine = create_engine(test_url, future=True)
        names = set(inspect(engine).get_table_names())
        engine.dispose()
        assert "sync_jobs" not in names
        assert "users" in names
    finally:
        _cleanup(admin, monkeypatch)


@requires_postgres
def test_postgres_0004_backfills_historical_raw_programme(monkeypatch):
    admin, test_url = _prepare_verify_db(_admin_url())
    _point_alembic(monkeypatch, test_url)
    try:
        cfg = _alembic_cfg()
        command.upgrade(cfg, "0003_phase12_corrections")
        engine = create_engine(test_url, future=True)
        metadata = MetaData()
        metadata.reflect(bind=engine)
        programme_id = uuid4()
        org_unit_id = uuid4()
        mapping_id = uuid4()
        raw_id = uuid4()
        with engine.begin() as conn:
            conn.execute(
                metadata.tables["programmes"].insert().values(
                    id=programme_id,
                    code="TEST_PROGRAMME",
                    name="Synthetic migration programme",
                    first_release=False,
                    active=True,
                    sensitive=False,
                )
            )
            conn.execute(
                metadata.tables["org_units"].insert().values(
                    id=org_unit_id,
                    code="TEST_OU",
                    name="Synthetic migration unit",
                    level_type="district",
                    path="/TEST_OU",
                    active=True,
                )
            )
            conn.execute(
                metadata.tables["source_mappings"].insert().values(
                    id=mapping_id,
                    internal_source_key="TEST_KEY",
                    programme_id=programme_id,
                    dhis2_item_uid="TEST_UID_ITEM",
                    item_kind="data_element",
                    category_option_combo_uid="TEST_UID_COC",
                    mapping_version="v1",
                    enabled=True,
                )
            )
            conn.execute(
                metadata.tables["raw_aggregate_values"].insert().values(
                    id=raw_id,
                    source_system="dhis2",
                    org_unit_id=org_unit_id,
                    period="202407",
                    source_metric_id="TEST_UID_ITEM",
                    internal_source_key="TEST_KEY",
                    dhis2_item_uid="TEST_UID_ITEM",
                    category_option_combo_uid="TEST_UID_COC",
                    value=1,
                    extracted_at=datetime.now(UTC),
                    mapping_version="v1",
                    is_current=True,
                    provenance={"mapping_id": str(mapping_id)},
                    value_invalid=False,
                )
            )
        engine.dispose()
        command.upgrade(cfg, "0004_phase12_audit_fixes")
        engine = create_engine(test_url, future=True)
        metadata = MetaData()
        metadata.reflect(bind=engine)
        with engine.connect() as conn:
            stored_programme = conn.execute(
                select(metadata.tables["raw_aggregate_values"].c.programme_id).where(
                    metadata.tables["raw_aggregate_values"].c.id == raw_id
                )
            ).scalar_one()
        engine.dispose()
        assert stored_programme == programme_id
    finally:
        _cleanup(admin, monkeypatch)


@requires_postgres
def test_postgres_0001_to_head(monkeypatch):
    admin, test_url = _prepare_verify_db(_admin_url())
    _point_alembic(monkeypatch, test_url)
    try:
        cfg = _alembic_cfg()
        command.upgrade(cfg, "0001_phase1_foundation")
        command.upgrade(cfg, "head")
        engine = create_engine(test_url, future=True)
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        engine.dispose()
        assert version == HEAD_REVISION
    finally:
        _cleanup(admin, monkeypatch)


@requires_postgres
def test_postgres_0001_to_0002_to_head(monkeypatch):
    admin, test_url = _prepare_verify_db(_admin_url())
    _point_alembic(monkeypatch, test_url)
    try:
        cfg = _alembic_cfg()
        command.upgrade(cfg, "0001_phase1_foundation")
        command.upgrade(cfg, "0002_phase2_engines")
        command.upgrade(cfg, "head")
        engine = create_engine(test_url, future=True)
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        names = set(inspect(engine).get_table_names())
        engine.dispose()
        assert version == HEAD_REVISION
        assert "sync_jobs" in names
        assert "auth_sessions" in names
    finally:
        _cleanup(admin, monkeypatch)


@requires_postgres
def test_postgres_old_0002_to_0003_to_0004(monkeypatch):
    admin, test_url = _prepare_verify_db(_admin_url())
    _point_alembic(monkeypatch, test_url)
    try:
        cfg = _alembic_cfg()
        command.upgrade(cfg, "0002_phase2_engines")
        command.upgrade(cfg, "0003_phase12_corrections")
        command.upgrade(cfg, "0004_phase12_audit_fixes")
        engine = create_engine(test_url, future=True)
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        engine.dispose()
        assert version == "0004_phase12_audit_fixes"
    finally:
        _cleanup(admin, monkeypatch)


@requires_postgres
def test_postgres_upgrade_after_downgrade(monkeypatch):
    admin, test_url = _prepare_verify_db(_admin_url())
    _point_alembic(monkeypatch, test_url)
    try:
        cfg = _alembic_cfg()
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "0003_phase12_corrections")
        command.upgrade(cfg, "head")
        engine = create_engine(test_url, future=True)
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        columns = {column["name"] for column in inspect(engine).get_columns("raw_aggregate_values")}
        engine.dispose()
        assert version == HEAD_REVISION
        assert "programme_id" in columns
    finally:
        _cleanup(admin, monkeypatch)


@requires_postgres
def test_postgres_0004_ambiguous_backfill_fails(monkeypatch):
    admin, test_url = _prepare_verify_db(_admin_url())
    _point_alembic(monkeypatch, test_url)
    try:
        cfg = _alembic_cfg()
        command.upgrade(cfg, "0003_phase12_corrections")
        engine = create_engine(test_url, future=True)
        metadata = MetaData()
        metadata.reflect(bind=engine)
        programme_a = uuid4()
        programme_b = uuid4()
        org_unit_id = uuid4()
        with engine.begin() as conn:
            for programme_id, code in ((programme_a, "TEST_A"), (programme_b, "TEST_B")):
                conn.execute(
                    metadata.tables["programmes"].insert().values(
                        id=programme_id,
                        code=code,
                        name=f"Synthetic {code}",
                        first_release=False,
                        active=True,
                        sensitive=False,
                    )
                )
            conn.execute(
                metadata.tables["org_units"].insert().values(
                    id=org_unit_id,
                    code="TEST_OU_AMBIG",
                    name="Synthetic ambiguous unit",
                    level_type="district",
                    path="/TEST_OU_AMBIG",
                    active=True,
                )
            )
            for programme_id in (programme_a, programme_b):
                conn.execute(
                    metadata.tables["source_mappings"].insert().values(
                        id=uuid4(),
                        internal_source_key="TEST_KEY",
                        programme_id=programme_id,
                        dhis2_item_uid="TEST_UID_ITEM",
                        item_kind="data_element",
                        category_option_combo_uid="TEST_UID_COC",
                        mapping_version="v1",
                        enabled=True,
                    )
                )
            conn.execute(
                metadata.tables["raw_aggregate_values"].insert().values(
                    id=uuid4(),
                    source_system="dhis2",
                    org_unit_id=org_unit_id,
                    period="202407",
                    source_metric_id="TEST_UID_ITEM",
                    internal_source_key="TEST_KEY",
                    dhis2_item_uid="TEST_UID_ITEM",
                    category_option_combo_uid="TEST_UID_COC",
                    value=1,
                    extracted_at=datetime.now(UTC),
                    mapping_version="v1",
                    is_current=True,
                    provenance={},
                    value_invalid=False,
                )
            )
        engine.dispose()
        with pytest.raises(Exception, match="Cannot infer programme"):
            command.upgrade(cfg, "0004_phase12_audit_fixes")
    finally:
        _cleanup(admin, monkeypatch)


@requires_postgres
def test_postgres_0005_to_0006(monkeypatch):
    admin, test_url = _prepare_verify_db(_admin_url())
    _point_alembic(monkeypatch, test_url)
    try:
        cfg = _alembic_cfg()
        command.upgrade(cfg, "0005_phase567_ai_publishing")
        command.upgrade(cfg, "0006_corrective_snapshots")
        engine = create_engine(test_url, future=True)
        names = set(inspect(engine).get_table_names())
        event_cols = {column["name"] for column in inspect(engine).get_columns("raw_event_snapshots")}
        export_cols = {column["name"] for column in inspect(engine).get_columns("export_jobs")}
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        engine.dispose()
        assert version == "0006_corrective_snapshots"
        assert "analysis_snapshots" in names
        assert "programme_id" in event_cols
        assert "analysis_snapshot_id" in export_cols
    finally:
        _cleanup(admin, monkeypatch)


@requires_postgres
def test_postgres_0006_to_0007(monkeypatch):
    admin, test_url = _prepare_verify_db(_admin_url())
    _point_alembic(monkeypatch, test_url)
    try:
        cfg = _alembic_cfg()
        command.upgrade(cfg, "0006_corrective_snapshots")
        command.upgrade(cfg, "0007_amendment_corrections")
        engine = create_engine(test_url, future=True)
        inspector = inspect(engine)
        names = set(inspector.get_table_names())
        rule_cols = {column["name"] for column in inspector.get_columns("period_population_rules")}
        snapshot_indexes = {index["name"] for index in inspector.get_indexes("analysis_snapshots")}
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        engine.dispose()
        assert version == "0007_amendment_corrections"
        assert "population_source_aliases" in names
        assert {"scope_kind", "applies_to_period_kinds", "approval_status"} <= rule_cols
        assert "uq_analysis_snapshots_user_request" in snapshot_indexes
        command.downgrade(cfg, "0006_corrective_snapshots")
        engine = create_engine(test_url, future=True)
        names = set(inspect(engine).get_table_names())
        engine.dispose()
        assert "population_source_aliases" not in names
    finally:
        _cleanup(admin, monkeypatch)


def _legacy_export_rows(engine) -> dict:
    """Insert 0007-shaped export jobs, including duplicate live rows for one key."""
    metadata = MetaData()
    metadata.reflect(bind=engine)
    users, jobs = metadata.tables["users"], metadata.tables["export_jobs"]

    def ident(value):
        # Reflected SQLite UUID columns are CHAR(32); PostgreSQL binds UUID objects natively.
        return value.hex if engine.dialect.name == "sqlite" else value

    user_id = uuid4()
    key = f"{user_id}:{uuid4()}:excel"
    older, newer, failed, queued = uuid4(), uuid4(), uuid4(), uuid4()
    stamp = datetime(2026, 1, 1, tzinfo=UTC)
    with engine.begin() as conn:
        conn.execute(
            users.insert().values(
                id=ident(user_id),
                username="legacy.export.user",
                display_name="Synthetic legacy export user",
                password_hash="not-a-real-hash",
                is_active=True,
                is_system_admin=False,
                identity_provider="local_dev",
                created_at=stamp,
                updated_at=stamp,
            )
        )
        for job_id, status, created in (
            (older, "succeeded", datetime(2026, 1, 1, tzinfo=UTC)),
            (newer, "succeeded", datetime(2026, 1, 2, tzinfo=UTC)),
            (failed, "failed", datetime(2026, 1, 3, tzinfo=UTC)),
            (queued, "queued", datetime(2026, 1, 4, tzinfo=UTC)),
        ):
            conn.execute(
                jobs.insert().values(
                    id=ident(job_id),
                    user_id=ident(user_id),
                    export_type="excel",
                    status=status,
                    idempotency_key=key if job_id != queued else f"{user_id}:{uuid4()}:excel",
                    created_at=created,
                    updated_at=created,
                )
            )
    return {"older": older, "newer": newer, "failed": failed, "queued": queued, "key": key}


def _export_state(engine) -> dict:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id, active_key, dispatch_state, attempt_count, retry_scheduled FROM export_jobs")
        ).all()
    return {str(row[0]).replace("-", ""): row for row in rows}


@requires_postgres
def test_postgres_0007_to_0008_backfills_one_live_export_per_key(monkeypatch):
    admin, test_url = _prepare_verify_db(_admin_url())
    _point_alembic(monkeypatch, test_url)
    try:
        cfg = _alembic_cfg()
        command.upgrade(cfg, "0007_amendment_corrections")
        engine = create_engine(test_url, future=True)
        legacy = _legacy_export_rows(engine)
        engine.dispose()
        command.upgrade(cfg, "0008_export_queue_durability")
        engine = create_engine(test_url, future=True)
        state = _export_state(engine)
        indexes = {index["name"]: index for index in inspect(engine).get_indexes("export_jobs")}
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            length = conn.execute(
                text(
                    "SELECT character_maximum_length FROM information_schema.columns "
                    "WHERE table_name = 'export_jobs' AND column_name = 'idempotency_key'"
                )
            ).scalar_one()
        engine.dispose()
        assert version == "0008_export_queue_durability"
        assert length == 200
        assert indexes["uq_export_jobs_active_key"]["unique"]
        assert state[legacy["newer"].hex][1] == legacy["key"]
        assert state[legacy["older"].hex][1] is None
        assert state[legacy["failed"].hex][1] is None
        assert state[legacy["queued"].hex][1] is not None
        assert {row[2] for row in state.values()} == {"legacy"}
        assert state[legacy["queued"].hex][3] == 0 and state[legacy["newer"].hex][3] == 1
        command.downgrade(cfg, "0007_amendment_corrections")
        engine = create_engine(test_url, future=True)
        columns = {column["name"] for column in inspect(engine).get_columns("export_jobs")}
        engine.dispose()
        assert "active_key" not in columns and "attempt_count" not in columns
        command.upgrade(cfg, "head")
        engine = create_engine(test_url, future=True)
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        engine.dispose()
        assert version == HEAD_REVISION
    finally:
        _cleanup(admin, monkeypatch)


@requires_postgres
def test_postgres_model_migration_parity(monkeypatch):
    from app.db.base import Base
    from app.models import AnalysisSnapshot, ExportJob, RawEventSnapshot  # noqa: F401

    admin, test_url = _prepare_verify_db(_admin_url())
    _point_alembic(monkeypatch, test_url)
    try:
        command.upgrade(_alembic_cfg(), "head")
        engine = create_engine(test_url, future=True)
        db_tables = set(inspect(engine).get_table_names()) - {"alembic_version"}
        model_tables = set(Base.metadata.tables)
        missing = model_tables - db_tables
        assert missing == set(), f"Models missing from Alembic head: {sorted(missing)}"
        for table in (
            "analysis_snapshots",
            "export_jobs",
            "raw_event_snapshots",
            "ai_requests",
            "period_population_rules",
            "sync_jobs",
            "population_versions",
            "population_values",
            "population_source_aliases",
            "calculated_values",
        ):
            db_cols = {column["name"] for column in inspect(engine).get_columns(table)}
            model_cols = set(Base.metadata.tables[table].c.keys())
            assert model_cols <= db_cols, f"{table} missing columns {sorted(model_cols - db_cols)}"
        engine.dispose()
    finally:
        _cleanup(admin, monkeypatch)

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from alembic.config import Config
from alembic.script import ScriptDirectory
from historical.phase1 import PHASE1_TABLES
from historical.phase2 import PHASE2_TABLES
from sqlalchemy import MetaData, create_engine, inspect, select, text

from app.db.base import Base

REQUIRED_TABLES = set(PHASE1_TABLES) | set(PHASE2_TABLES) | {"auth_sessions", "login_attempts"}


def _alembic_cfg() -> Config:
    return Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_metadata_create_all_applies_required_tables(engine):
    names = set(inspect(engine).get_table_names())
    missing = REQUIRED_TABLES - names
    assert missing == set(), f"Missing tables: {sorted(missing)}"


def test_sensitive_event_column_comment_present():
    table = Base.metadata.tables["raw_event_snapshots"]
    assert "UID" in (table.c.event_uid.comment or "")
    assert "names" in (table.c.data_values.comment or "").lower()


HEAD_REVISION = "0011_population_import_staging"


def test_alembic_head_is_corrective_revision():
    script = ScriptDirectory.from_config(_alembic_cfg())
    assert script.get_current_head() == HEAD_REVISION


def test_historical_revisions_do_not_import_orm_models():
    root = Path(__file__).resolve().parents[1] / "alembic"
    files = [
        root / "versions" / "0001_phase1_foundation.py",
        root / "versions" / "0002_phase2_engines.py",
        root / "versions" / "0003_phase12_corrections.py",
        root / "versions" / "0004_phase12_audit_fixes.py",
        root / "versions" / "0005_phase567_ai_publishing.py",
        root / "versions" / "0006_corrective_snapshots.py",
        root / "versions" / "0007_amendment_corrections.py",
        root / "versions" / "0008_export_queue_durability.py",
        root / "versions" / "0009_retention_and_artifact_storage.py",
        root / "versions" / "0010_denominator_provenance.py",
        root / "versions" / "0011_population_import_staging.py",
        root / "historical" / "phase1.py",
        root / "historical" / "phase2.py",
        root / "historical" / "phase12_corrections.py",
        root / "historical" / "phase12_audit_fixes.py",
    ]
    for path in files:
        text_source = _source(path)
        assert "from app.models" not in text_source
        assert "import app.models" not in text_source
        assert "Base.metadata.create_all" not in text_source
        assert "column.copy" not in text_source


def test_alembic_upgrade_on_sqlite(tmp_path, monkeypatch):
    db_path = tmp_path / "migrate.db"
    url = f"sqlite+pysqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    from app.config import get_settings
    from app.db.session import reset_engine

    get_settings.cache_clear()
    reset_engine()
    from alembic import command

    cfg = _alembic_cfg()
    command.upgrade(cfg, "head")
    from sqlalchemy import create_engine

    engine = create_engine(url)
    names = set(inspect(engine).get_table_names())
    engine.dispose()
    get_settings.cache_clear()
    reset_engine()
    assert "users" in names
    assert "sync_jobs" in names
    assert "auth_sessions" in names
    assert "alembic_version" in names
    assert "analysis_snapshots" in names


def test_revision_0001_creates_only_phase1_tables(tmp_path, monkeypatch):
    db_path = tmp_path / "p1.db"
    url = f"sqlite+pysqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    from alembic import command
    from sqlalchemy import create_engine

    from app.config import get_settings
    from app.db.session import reset_engine

    get_settings.cache_clear()
    reset_engine()
    command.upgrade(_alembic_cfg(), "0001_phase1_foundation")
    engine = create_engine(url)
    names = set(inspect(engine).get_table_names()) - {"alembic_version"}
    engine.dispose()
    get_settings.cache_clear()
    reset_engine()
    assert names == set(PHASE1_TABLES)
    assert not (set(PHASE2_TABLES) & names)
    assert "auth_sessions" not in names


def test_revision_0001_to_0002_creates_phase2_delta(tmp_path, monkeypatch):
    db_path = tmp_path / "p2.db"
    url = f"sqlite+pysqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    from alembic import command
    from sqlalchemy import create_engine

    from app.config import get_settings
    from app.db.session import reset_engine

    get_settings.cache_clear()
    reset_engine()
    cfg = _alembic_cfg()
    command.upgrade(cfg, "0001_phase1_foundation")
    command.upgrade(cfg, "0002_phase2_engines")
    engine = create_engine(url)
    names = set(inspect(engine).get_table_names())
    engine.dispose()
    get_settings.cache_clear()
    reset_engine()
    assert set(PHASE2_TABLES) <= names
    assert "auth_sessions" not in names


def test_upgrade_previous_head_to_audit_fix_head(tmp_path, monkeypatch):
    db_path = tmp_path / "p3.db"
    url = f"sqlite+pysqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    from alembic import command
    from sqlalchemy import create_engine

    from app.config import get_settings
    from app.db.session import reset_engine

    get_settings.cache_clear()
    reset_engine()
    cfg = _alembic_cfg()
    command.upgrade(cfg, "0003_phase12_corrections")
    command.upgrade(cfg, "0004_phase12_audit_fixes")
    engine = create_engine(url)
    names = set(inspect(engine).get_table_names())
    with engine.connect() as conn:
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    engine.dispose()
    get_settings.cache_clear()
    reset_engine()
    assert version == "0004_phase12_audit_fixes"
    assert "auth_sessions" in names
    assert "login_attempts" in names
    assert "programme_id" in {column["name"] for column in inspect(engine).get_columns("raw_aggregate_values")}


def test_upgrade_0004_to_phase567_head(tmp_path, monkeypatch):
    db_path = tmp_path / "p5.db"
    url = f"sqlite+pysqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    from alembic import command
    from sqlalchemy import create_engine

    from app.config import get_settings
    from app.db.session import reset_engine

    get_settings.cache_clear()
    reset_engine()
    cfg = _alembic_cfg()
    command.upgrade(cfg, "0004_phase12_audit_fixes")
    command.upgrade(cfg, "0005_phase567_ai_publishing")
    engine = create_engine(url)
    export_cols = {column["name"] for column in inspect(engine).get_columns("export_jobs")}
    ai_cols = {column["name"] for column in inspect(engine).get_columns("ai_requests")}
    with engine.connect() as conn:
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    engine.dispose()
    get_settings.cache_clear()
    reset_engine()
    assert version == "0005_phase567_ai_publishing"
    assert {"file_path", "module", "comparison_period", "metadata_json"} <= export_cols
    assert {"prompt_version", "fallback_used", "error_code", "response_json"} <= ai_cols


def test_downgrade_is_explicit(tmp_path, monkeypatch):
    db_path = tmp_path / "down.db"
    url = f"sqlite+pysqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    from alembic import command
    from sqlalchemy import create_engine

    from app.config import get_settings
    from app.db.session import reset_engine

    get_settings.cache_clear()
    reset_engine()
    cfg = _alembic_cfg()
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0002_phase2_engines")
    engine = create_engine(url)
    names = set(inspect(engine).get_table_names())
    engine.dispose()
    assert "auth_sessions" not in names
    assert "sync_jobs" in names
    command.downgrade(cfg, "0001_phase1_foundation")
    engine = create_engine(url)
    names = set(inspect(engine).get_table_names())
    engine.dispose()
    get_settings.cache_clear()
    reset_engine()
    assert "sync_jobs" not in names
    assert "users" in names


def test_0004_backfills_historical_raw_programme_from_mapping(tmp_path, monkeypatch):
    db_path = tmp_path / "backfill.db"
    url = f"sqlite+pysqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    from alembic import command

    from app.config import get_settings
    from app.db.session import reset_engine

    get_settings.cache_clear()
    reset_engine()
    cfg = _alembic_cfg()
    command.upgrade(cfg, "0003_phase12_corrections")
    engine = create_engine(url)
    metadata = MetaData()
    metadata.reflect(bind=engine)
    programme_id = uuid4()
    org_unit_id = uuid4()
    mapping_id = uuid4()
    raw_id = uuid4()
    with engine.begin() as conn:
        conn.execute(
            metadata.tables["programmes"].insert().values(
                id=programme_id.hex,
                code="TEST_PROGRAMME",
                name="Synthetic migration programme",
                first_release=False,
                active=True,
                sensitive=False,
            )
        )
        conn.execute(
            metadata.tables["org_units"].insert().values(
                id=org_unit_id.hex,
                code="TEST_OU",
                name="Synthetic migration unit",
                level_type="district",
                path="/TEST_OU",
                active=True,
            )
        )
        conn.execute(
            metadata.tables["source_mappings"].insert().values(
                id=mapping_id.hex,
                internal_source_key="TEST_KEY",
                programme_id=programme_id.hex,
                dhis2_item_uid="TEST_UID_ITEM",
                item_kind="data_element",
                category_option_combo_uid="TEST_UID_COC",
                mapping_version="v1",
                enabled=True,
            )
        )
        conn.execute(
            metadata.tables["raw_aggregate_values"].insert().values(
                id=raw_id.hex,
                source_system="dhis2",
                org_unit_id=org_unit_id.hex,
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
    engine = create_engine(url)
    metadata = MetaData()
    metadata.reflect(bind=engine)
    with engine.connect() as conn:
        stored_programme = conn.execute(
            select(metadata.tables["raw_aggregate_values"].c.programme_id).where(
                metadata.tables["raw_aggregate_values"].c.id == raw_id.hex
            )
        ).scalar_one()
    engine.dispose()
    get_settings.cache_clear()
    reset_engine()
    assert str(stored_programme).replace("-", "") == programme_id.hex


def test_upgrade_0001_to_head(tmp_path, monkeypatch):
    db_path = tmp_path / "p1head.db"
    url = f"sqlite+pysqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    from alembic import command
    from sqlalchemy import create_engine

    from app.config import get_settings
    from app.db.session import reset_engine

    get_settings.cache_clear()
    reset_engine()
    cfg = _alembic_cfg()
    command.upgrade(cfg, "0001_phase1_foundation")
    command.upgrade(cfg, "head")
    engine = create_engine(url)
    with engine.connect() as conn:
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    engine.dispose()
    get_settings.cache_clear()
    reset_engine()
    assert version == HEAD_REVISION


def test_upgrade_0005_to_0006(tmp_path, monkeypatch):
    db_path = tmp_path / "p6.db"
    url = f"sqlite+pysqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    from alembic import command
    from sqlalchemy import create_engine

    from app.config import get_settings
    from app.db.session import reset_engine

    get_settings.cache_clear()
    reset_engine()
    cfg = _alembic_cfg()
    command.upgrade(cfg, "0005_phase567_ai_publishing")
    command.upgrade(cfg, "0006_corrective_snapshots")
    engine = create_engine(url)
    names = set(inspect(engine).get_table_names())
    event_cols = {column["name"] for column in inspect(engine).get_columns("raw_event_snapshots")}
    export_cols = {column["name"] for column in inspect(engine).get_columns("export_jobs")}
    with engine.connect() as conn:
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    engine.dispose()
    get_settings.cache_clear()
    reset_engine()
    assert version == "0006_corrective_snapshots"
    assert "analysis_snapshots" in names
    assert "programme_id" in event_cols
    assert "analysis_snapshot_id" in export_cols


def test_upgrade_0006_to_0007_preserves_fy_rules_as_fy_only(tmp_path, monkeypatch):
    db_path = tmp_path / "p7.db"
    url = f"sqlite+pysqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    from alembic import command
    from sqlalchemy import create_engine

    from app.config import get_settings
    from app.db.session import reset_engine

    get_settings.cache_clear()
    reset_engine()
    cfg = _alembic_cfg()
    command.upgrade(cfg, "0006_corrective_snapshots")
    engine = create_engine(url)
    metadata = MetaData()
    metadata.reflect(bind=engine)
    with engine.begin() as conn:
        conn.execute(
            metadata.tables["period_population_rules"].insert().values(
                id=uuid4().hex,
                financial_year_key="FY2025/26",
                population_year=2025,
            )
        )
    engine.dispose()
    command.upgrade(cfg, "0007_amendment_corrections")
    engine = create_engine(url)
    inspector = inspect(engine)
    snapshot_cols = {column["name"] for column in inspector.get_columns("analysis_snapshots")}
    rule_cols = {column["name"] for column in inspector.get_columns("period_population_rules")}
    job_cols = {column["name"] for column in inspector.get_columns("sync_jobs")}
    value_cols = {column["name"] for column in inspector.get_columns("calculated_values")}
    names = set(inspector.get_table_names())
    with engine.connect() as conn:
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        rule = conn.execute(
            text("SELECT scope_kind, applies_to_period_kinds, approval_status FROM period_population_rules")
        ).one()
    engine.dispose()
    get_settings.cache_clear()
    reset_engine()
    assert version == "0007_amendment_corrections"
    assert "idempotency_key" in snapshot_cols
    assert {"scope_kind", "applies_to_period_kinds", "approval_status"} <= rule_cols
    assert {"window_start", "window_end"} <= job_cols
    assert {"reason_code", "event_snapshot_ids", "event_coverage"} <= value_cols
    assert "population_source_aliases" in names
    assert rule[0] == "financial_year"
    assert rule[1] is None
    assert rule[2] == "approved"


def test_upgrade_0007_to_0008_backfills_one_live_export_per_key(tmp_path, monkeypatch):
    db_path = tmp_path / "p8.db"
    url = f"sqlite+pysqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    from alembic import command
    from sqlalchemy import create_engine

    from app.config import get_settings
    from app.db.session import reset_engine
    from tests.test_postgres_migrations import _export_state, _legacy_export_rows

    get_settings.cache_clear()
    reset_engine()
    cfg = _alembic_cfg()
    command.upgrade(cfg, "0007_amendment_corrections")
    engine = create_engine(url)
    legacy = _legacy_export_rows(engine)
    engine.dispose()
    command.upgrade(cfg, "0008_export_queue_durability")
    engine = create_engine(url)
    state = _export_state(engine)
    indexes = {index["name"]: index for index in inspect(engine).get_indexes("export_jobs")}
    with engine.connect() as conn:
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    engine.dispose()
    assert version == "0008_export_queue_durability"

    assert indexes["uq_export_jobs_active_key"]["unique"]
    assert state[legacy["newer"].hex][1] == legacy["key"]
    assert state[legacy["older"].hex][1] is None
    assert state[legacy["failed"].hex][1] is None
    assert {row[2] for row in state.values()} == {"legacy"}
    command.downgrade(cfg, "0007_amendment_corrections")
    command.upgrade(cfg, "head")
    engine = create_engine(url)
    with engine.connect() as conn:
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    engine.dispose()
    get_settings.cache_clear()
    reset_engine()
    assert version == HEAD_REVISION


def test_upgrade_after_downgrade(tmp_path, monkeypatch):
    db_path = tmp_path / "updown.db"
    url = f"sqlite+pysqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    from alembic import command
    from sqlalchemy import create_engine

    from app.config import get_settings
    from app.db.session import reset_engine

    get_settings.cache_clear()
    reset_engine()
    cfg = _alembic_cfg()
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0003_phase12_corrections")
    command.upgrade(cfg, "head")
    engine = create_engine(url)
    with engine.connect() as conn:
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    columns = {column["name"] for column in inspect(engine).get_columns("raw_aggregate_values")}
    engine.dispose()
    get_settings.cache_clear()
    reset_engine()
    assert version == HEAD_REVISION
    assert "programme_id" in columns


def test_0004_ambiguous_backfill_fails(tmp_path, monkeypatch):
    db_path = tmp_path / "ambig.db"
    url = f"sqlite+pysqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    import pytest
    from alembic import command

    from app.config import get_settings
    from app.db.session import reset_engine

    get_settings.cache_clear()
    reset_engine()
    cfg = _alembic_cfg()
    command.upgrade(cfg, "0003_phase12_corrections")
    engine = create_engine(url)
    metadata = MetaData()
    metadata.reflect(bind=engine)
    programme_a = uuid4()
    programme_b = uuid4()
    org_unit_id = uuid4()
    with engine.begin() as conn:
        for programme_id, code in ((programme_a, "TEST_A"), (programme_b, "TEST_B")):
            conn.execute(
                metadata.tables["programmes"].insert().values(
                    id=programme_id.hex,
                    code=code,
                    name=f"Synthetic {code}",
                    first_release=False,
                    active=True,
                    sensitive=False,
                )
            )
        conn.execute(
            metadata.tables["org_units"].insert().values(
                id=org_unit_id.hex,
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
                    id=uuid4().hex,
                    internal_source_key="TEST_KEY",
                    programme_id=programme_id.hex,
                    dhis2_item_uid="TEST_UID_ITEM",
                    item_kind="data_element",
                    category_option_combo_uid="TEST_UID_COC",
                    mapping_version="v1",
                    enabled=True,
                )
            )
        conn.execute(
            metadata.tables["raw_aggregate_values"].insert().values(
                id=uuid4().hex,
                source_system="dhis2",
                org_unit_id=org_unit_id.hex,
                period="202407",
                source_metric_id="TEST_UID_ITEM",
                internal_source_key="TEST_KEY",
                dhis2_item_uid="TEST_UID_ITEM",
                category_option_combo_uid="TEST_UID_COC",
                value=1,
                extracted_at=datetime.now(UTC),
                mapping_version="v1",
                is_current=True,
                provenance="{}",
                value_invalid=False,
            )
        )
    engine.dispose()
    with pytest.raises(Exception, match="Cannot infer programme"):
        command.upgrade(cfg, "0004_phase12_audit_fixes")
    get_settings.cache_clear()
    reset_engine()

"""Neon-style URLs, the psycopg 3 driver and TLS for both the runtime and migrations (work package D).

No network: engines are built but never connected, except in the PostgreSQL-only tests at the
end, which use the disposable cluster named by HPIP_POSTGRES_TEST_URL.
"""

from __future__ import annotations

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from app.config import Settings, validate_runtime_settings
from app.db import session as session_module
from app.db.urls import connect_args, effective_sslmode, normalise_database_url, url_sslmode
from tests.test_runtime_gates import PRODUCTION_BASE

# Neon-shaped examples. Hosts and passwords are invented and never contacted.
POOLED = "postgresql://hpip_app:Np4ss-Word@ep-quiet-lake-a1b2c3-pooler.eu-central-1.aws.neon.tech/hpip?sslmode=require&channel_binding=require"  # noqa: E501
DIRECT = "postgresql://hpip_app:Np4ss-Word@ep-quiet-lake-a1b2c3.eu-central-1.aws.neon.tech/hpip?sslmode=require"
SECRET = "Np4ss-Word"


def _production(**overrides) -> Settings:
    return Settings(**{**PRODUCTION_BASE, "db_sslmode": "", **overrides})


@pytest.mark.parametrize(
    ("raw", "expected_prefix"),
    [
        ("postgresql://u:p@h:5432/db", "postgresql+psycopg://"),
        ("postgres://u:p@h:5432/db", "postgresql+psycopg://"),
        ("POSTGRESQL://u:p@h/db", "postgresql+psycopg://"),
        ("  postgresql://u:p@h/db  ", "postgresql+psycopg://"),
        ("postgresql+psycopg://u:p@h/db", "postgresql+psycopg://"),
        ("sqlite+pysqlite:///./hpip.db", "sqlite+pysqlite://"),
    ],
)
def test_plain_urls_are_normalised_to_psycopg3_idempotently(raw, expected_prefix):
    once = normalise_database_url(raw)
    assert once.startswith(expected_prefix)
    assert normalise_database_url(once) == once


def test_neon_pooled_and_direct_urls_keep_host_query_and_credentials():
    settings = _production(database_url=POOLED, migration_database_url=DIRECT)
    assert settings.database_url.startswith("postgresql+psycopg://")
    assert settings.migration_database_url.startswith("postgresql+psycopg://")
    pooled = make_url(settings.database_url)
    assert pooled.drivername == "postgresql+psycopg"
    assert pooled.host.endswith("-pooler.eu-central-1.aws.neon.tech")
    assert pooled.query["channel_binding"] == "require" and pooled.query["sslmode"] == "require"
    assert pooled.password == SECRET
    assert validate_runtime_settings(settings) == []
    assert session_module.migration_url(settings) == settings.migration_database_url


def test_special_characters_in_percent_encoded_passwords_survive():
    raw = "postgresql://hpip:p%40ss%3Aw%2Frd%25%23x@db.example:5432/hpip?sslmode=require"
    settings = _production(database_url=raw)
    assert make_url(settings.database_url).password == "p@ss:w/rd%#x"
    assert validate_runtime_settings(settings) == []
    engine = session_module.create_db_engine(settings)
    try:
        assert engine.url.password == "p@ss:w/rd%#x"
    finally:
        engine.dispose()


def test_a_psycopg2_url_is_rejected_with_an_actionable_message_and_no_secret():
    errors = validate_runtime_settings(
        _production(database_url=f"postgresql+psycopg2://hpip:{SECRET}@db/hpip?sslmode=require")
    )
    assert any("postgresql+psycopg driver" in error for error in errors), errors
    assert SECRET not in " ".join(errors)
    migration = validate_runtime_settings(
        _production(
            database_url=DIRECT,
            migration_database_url=f"postgresql+pg8000://hpip:{SECRET}@db/hpip?sslmode=require",
        )
    )
    assert any(error.startswith("MIGRATION_DATABASE_URL must use") for error in migration), migration


@pytest.mark.parametrize(
    ("overrides", "fragment"),
    [
        ({"database_url": "postgresql://h:s@db/hpip"}, "DATABASE_URL must require TLS"),
        ({"database_url": "postgresql://h:s@db/hpip?sslmode=disable"}, "DATABASE_URL disables TLS"),
        ({"database_url": "postgresql://h:s@db/hpip?sslmode=prefer"}, "DATABASE_URL must require TLS"),
        (
            {"database_url": DIRECT, "migration_database_url": "postgresql://h:s@direct/hpip?sslmode=disable"},
            "MIGRATION_DATABASE_URL disables TLS",
        ),
        (
            {"database_url": DIRECT, "migration_database_url": "postgresql://h:s@direct/hpip"},
            "MIGRATION_DATABASE_URL must require TLS",
        ),
        (
            {"database_url": "postgresql://h:s@db/hpip?sslmode=prefer", "db_sslmode": "require"},
            "conflicts with DB_SSLMODE=require",
        ),
        ({"migration_database_url": "postgresql://"}, "MIGRATION_DATABASE_URL is malformed"),
    ],
)
def test_tls_is_required_for_both_runtime_and_migration_urls(overrides, fragment):
    base = {"database_url": DIRECT}
    errors = validate_runtime_settings(_production(**{**base, **overrides}))
    assert any(fragment in error for error in errors), errors
    assert SECRET not in " ".join(errors) and ":s@" not in " ".join(errors)


def test_db_sslmode_alone_satisfies_tls_for_urls_without_a_query():
    settings = _production(
        database_url="postgresql://h:s@pooler/hpip",
        migration_database_url="postgresql://h:s@direct/hpip",
        db_sslmode="require",
    )
    assert validate_runtime_settings(settings) == []


def test_private_network_opt_out_is_explicit():
    settings = _production(database_url="postgresql://h:s@db/hpip", db_require_ssl=False)
    assert validate_runtime_settings(settings) == []


def test_sslmode_precedence_is_url_first_then_setting():
    assert url_sslmode(DIRECT) == "require"
    assert effective_sslmode("postgresql+psycopg://h/db?sslmode=verify-full", "require") == "verify-full"
    assert effective_sslmode("postgresql+psycopg://h/db", "require") == "require"
    assert connect_args(DIRECT, sslmode="require", connect_timeout=7, application_name="hpip") == {
        "connect_timeout": 7,
        "application_name": "hpip",
    }
    assert connect_args("postgresql+psycopg://h/db", sslmode="require", connect_timeout=7, application_name="") == {
        "connect_timeout": 7,
        "sslmode": "require",
    }


def test_migration_engine_uses_nullpool_tls_and_timeout(monkeypatch):
    captured: dict = {}
    real = session_module.create_engine

    def spy(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return real(url, **kwargs)

    monkeypatch.setattr(session_module, "create_engine", spy)
    settings = _production(
        database_url="postgresql://h:s@pooler/hpip",
        migration_database_url="postgres://h:s@direct/hpip",
        db_sslmode="require",
        db_connect_timeout_seconds=9,
    )
    engine = session_module.create_migration_engine(settings)
    try:
        assert isinstance(engine.pool, NullPool)
        assert engine.dialect.driver == "psycopg"
        assert make_url(captured["url"]).host == "direct"
        assert captured["connect_args"]["sslmode"] == "require"
        assert captured["connect_args"]["connect_timeout"] == 9
        assert captured["connect_args"]["application_name"] == "hpip-migrations"
    finally:
        engine.dispose()


def test_runtime_engine_normalises_and_applies_the_same_arguments(monkeypatch):
    captured: dict = {}
    real = session_module.create_engine

    def spy(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return real(url, **kwargs)

    monkeypatch.setattr(session_module, "create_engine", spy)
    settings = _production(database_url="postgresql://h:s@pooler/hpip", db_sslmode="require")
    engine = session_module.create_db_engine(settings)
    try:
        assert engine.dialect.driver == "psycopg"
        assert captured["connect_args"]["sslmode"] == "require"
        assert captured["pool_size"] == settings.db_pool_size
    finally:
        engine.dispose()


def test_alembic_env_builds_its_engine_through_the_shared_factory():
    from pathlib import Path

    env = (Path(__file__).resolve().parents[1] / "alembic" / "env.py").read_text(encoding="utf-8")
    assert "create_migration_engine" in env
    assert "engine_from_config" not in env


# ---------------------------------------------------------------------------
# Real migration execution on the disposable PostgreSQL cluster
# ---------------------------------------------------------------------------


def _plain(url: str, password: str | None = None) -> str:
    """Rewrite the verification URL as a provider would hand it out: plain postgresql://."""
    parsed = make_url(url)
    if password is not None:
        parsed = parsed.set(password=password)
    rendered = parsed.render_as_string(hide_password=False)
    return "postgresql://" + rendered.split("://", 1)[1]


def test_postgres_migrations_run_from_a_plain_postgresql_url_and_honour_db_sslmode(monkeypatch):
    from alembic import command
    from sqlalchemy import create_engine, text

    from tests.test_postgres_migrations import (
        HEAD_REVISION,
        _admin_url,
        _alembic_cfg,
        _cleanup,
        _prepare_verify_db,
        postgres_available,
    )

    if not postgres_available:
        pytest.skip("PostgreSQL is not available (set HPIP_POSTGRES_TEST_URL to a disposable cluster)")
    from app.config import get_settings
    from app.db.session import reset_engine

    admin, test_url = _prepare_verify_db(_admin_url())
    # The disposable cluster uses trust authentication, so an arbitrary password with special
    # characters is accepted and lets us check it never appears in an error.
    marker = "Sp3cial@:/%#pw"
    plain = _plain(test_url, password=marker)
    try:
        monkeypatch.setenv("DATABASE_URL", plain)
        monkeypatch.delenv("MIGRATION_DATABASE_URL", raising=False)
        # The disposable cluster has no TLS: requiring it must make Alembic fail to connect,
        # which proves DB_SSLMODE reaches the migration engine.
        monkeypatch.setenv("DB_SSLMODE", "require")
        get_settings.cache_clear()
        reset_engine()
        with pytest.raises(Exception) as refused:
            command.upgrade(_alembic_cfg(), "head")
        assert "SSL" in str(refused.value) or "ssl" in str(refused.value)
        assert marker not in str(refused.value)

        monkeypatch.setenv("DB_SSLMODE", "disable")
        get_settings.cache_clear()
        reset_engine()
        command.upgrade(_alembic_cfg(), "head")
        engine = create_engine(test_url, future=True)
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        engine.dispose()
        assert version == HEAD_REVISION
    finally:
        monkeypatch.delenv("DB_SSLMODE", raising=False)
        _cleanup(admin, monkeypatch)

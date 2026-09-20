"""Production fails closed: rate limiting, broker/Redis configuration, API and worker startup."""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings, get_settings, validate_runtime_settings
from app.main import app
from app.models import OrgUnit
from app.services import rate_limit
from app.services.authorization import AuthorizationError
from tests.conftest import auth_header, login, query_dashboard
from tests.helpers import put_population, put_raw

PRODUCTION_BASE = {
    "_env_file": None,
    "app_env": "production",
    "database_url": "postgresql+psycopg://hpip:owner-supplied@db:5432/hpip",
    "auth_secret": "a-long-production-secret-value-that-is-not-a-placeholder",
    "seed_dev_data": False,
    "seed_password": "not-the-development-default",
    "auth_cookie_secure": True,
    "web_origin": "https://hpip.example.test",
    "allowed_origins": "https://hpip.example.test",
    "sync_execution": "queue",
    "export_eager": False,
    "rate_limit_backend": "redis",
    "redis_url": "redis://:owner-supplied@redis:6379/0",
    "celery_broker_url": "redis://:owner-supplied@redis:6379/1",
    "celery_result_backend": "redis://:owner-supplied@redis:6379/2",
        "db_sslmode": "require",
}


def _production(**overrides) -> Settings:
    return Settings(**{**PRODUCTION_BASE, **overrides})


class FakeRedis:
    """Shared in-memory counter standing in for one Redis used by several API processes."""

    store: dict[str, int] = {}
    expiries: dict[str, int] = {}

    def pipeline(self):
        return FakePipeline(self)


class FakePipeline:
    def __init__(self, client: FakeRedis) -> None:
        self.client = client
        self.ops: list[tuple] = []

    def incr(self, key):
        self.ops.append(("incr", key))

    def expire(self, key, seconds):
        self.ops.append(("expire", key, seconds))

    def execute(self):
        results = []
        for op in self.ops:
            if op[0] == "incr":
                FakeRedis.store[op[1]] = FakeRedis.store.get(op[1], 0) + 1
                results.append(FakeRedis.store[op[1]])
            else:
                FakeRedis.expiries[op[1]] = op[2]
                results.append(True)
        return results


def test_complete_production_configuration_has_no_queue_or_rate_limit_errors():
    errors = validate_runtime_settings(_production())
    assert not [error for error in errors if "CELERY" in error or "REDIS" in error or "RATE_LIMIT" in error]


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"celery_broker_url": ""}, "CELERY_BROKER_URL is required"),
        ({"celery_result_backend": ""}, "CELERY_RESULT_BACKEND is required"),
        ({"celery_broker_url": "memory://"}, "in-memory transport"),
        ({"celery_broker_url": "redis://:change-me@redis:6379/1"}, "placeholder credential"),
        ({"redis_url": ""}, "REDIS_URL is required"),
        ({"redis_url": "redis://:change-me@redis:6379/0"}, "REDIS_URL still uses"),
        ({"rate_limit_backend": "memory"}, "RATE_LIMIT_BACKEND=memory"),
        ({"rate_limit_backend": "local"}, "RATE_LIMIT_BACKEND must be"),
        ({"export_eager": True}, "EXPORT_EAGER"),
    ],
)
def test_production_rejects_missing_or_unsafe_queue_and_limiter_settings(overrides, expected):
    errors = validate_runtime_settings(_production(**overrides))
    assert any(expected in error for error in errors), errors


def test_default_settings_have_no_usable_broker_or_redis(monkeypatch):
    for name in ("REDIS_URL", "CELERY_BROKER_URL", "CELERY_RESULT_BACKEND", "RATE_LIMIT_BACKEND", "EXPORT_EAGER"):
        monkeypatch.delenv(name, raising=False)
    settings = Settings(_env_file=None)
    assert settings.redis_url == "" and settings.celery_broker_url == "" and settings.celery_result_backend == ""
    assert settings.rate_limit_backend == "redis"
    assert settings.export_eager is False


def test_memory_rate_limiter_is_refused_outside_development_and_test(monkeypatch):
    monkeypatch.setattr(get_settings(), "app_env", "production")
    monkeypatch.setattr(get_settings(), "rate_limit_backend", "memory")
    with pytest.raises(AuthorizationError) as error:
        rate_limit.check_rate(uuid4(), "export:excel", limit=5)
    assert error.value.code == "rate_limiter_unavailable"


def test_redis_limiter_without_url_fails_closed_instead_of_degrading(monkeypatch):
    monkeypatch.setattr(get_settings(), "rate_limit_backend", "redis")
    monkeypatch.setattr(get_settings(), "redis_url", "")
    with pytest.raises(AuthorizationError) as error:
        rate_limit.check_rate(uuid4(), "ai:ask", limit=5)
    assert error.value.code == "rate_limiter_unavailable"
    assert rate_limit._hits == {}


def test_unreachable_redis_fails_closed(monkeypatch):
    monkeypatch.setattr(get_settings(), "rate_limit_backend", "redis")
    monkeypatch.setattr(get_settings(), "redis_url", "redis://127.0.0.1:1/0")
    with pytest.raises(AuthorizationError) as error:
        rate_limit.check_rate(uuid4(), "ai:ask", limit=5)
    assert error.value.code == "rate_limiter_unavailable"
    assert rate_limit._hits == {}


def test_missing_redis_client_library_fails_closed(monkeypatch):
    monkeypatch.setattr(get_settings(), "rate_limit_backend", "redis")
    monkeypatch.setattr(get_settings(), "redis_url", "redis://redis:6379/0")

    def no_library():
        raise ImportError("redis is not installed")

    monkeypatch.setattr(rate_limit, "_redis_client", no_library)
    with pytest.raises(AuthorizationError) as error:
        rate_limit.check_rate(uuid4(), "export:excel", limit=5)
    assert error.value.code == "rate_limiter_unavailable"


def test_redis_limiter_shares_one_budget_across_processes(monkeypatch):
    monkeypatch.setattr(get_settings(), "rate_limit_backend", "redis")
    monkeypatch.setattr(get_settings(), "redis_url", "redis://redis:6379/0")
    FakeRedis.store.clear()
    FakeRedis.expiries.clear()
    monkeypatch.setattr(rate_limit, "_redis_client", FakeRedis)
    user = uuid4()
    rate_limit.check_rate(user, "export:excel", limit=2, window_seconds=60)
    rate_limit._hits.clear()  # a second API process has no local memory of the first
    rate_limit.check_rate(user, "export:excel", limit=2, window_seconds=60)
    with pytest.raises(AuthorizationError) as error:
        rate_limit.check_rate(user, "export:excel", limit=2, window_seconds=60)
    assert error.value.code == "rate_limited"
    (key,) = FakeRedis.store
    assert key.startswith(f"hpip:rate:export:excel:{user}:")
    assert FakeRedis.expiries[key] == 61


def test_limiter_outage_is_a_503_not_a_silent_pass(client, session, monkeypatch):
    pader = session.scalar(select(OrgUnit).where(OrgUnit.code == "PADER"))
    put_population(session, pader, 2024, 1_000_000, code="GATE_POP")
    put_raw(session, pader, "FY2024/25", "ANC1", 10_000)
    session.commit()
    headers = auth_header(login(client, "pader.focal"))
    dash = query_dashboard(client, headers, pader.id).json()
    monkeypatch.setattr(get_settings(), "rate_limit_backend", "redis")
    monkeypatch.setattr(get_settings(), "redis_url", "")
    response = client.post(
        "/exports/excel",
        json={
            "org_unit_id": str(pader.id),
            "period": "FY2024/25",
            "module": "anc",
            "analysis_snapshot_id": dash["analysis_snapshot_id"],
            "view_hash": dash["view_hash"],
        },
        headers=headers,
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "rate_limiter_unavailable"


def test_production_api_refuses_to_start_with_blocking_configuration(monkeypatch):
    import app.main as main

    broken = _production(celery_broker_url="", redis_url="")
    monkeypatch.setattr(main, "get_settings", lambda: broken)
    with pytest.raises(RuntimeError, match="CELERY_BROKER_URL"), TestClient(app):
        pass
    healthy = _production()
    monkeypatch.setattr(main, "get_settings", lambda: healthy)
    assert main.startup_configuration_errors() == []


def test_production_worker_refuses_to_start_without_broker(monkeypatch):
    from app.workers import celery_app as worker_module

    broken = _production(celery_broker_url="")
    monkeypatch.setattr(worker_module, "get_settings", lambda: broken)
    errors = worker_module.worker_configuration_errors()
    assert any("CELERY_BROKER_URL" in error for error in errors)
    with pytest.raises(RuntimeError, match="Worker configuration is invalid"):
        worker_module._refuse_invalid_worker_configuration()


def test_celery_is_never_configured_eagerly():
    from app.workers.celery_app import celery_app, celery_config

    assert celery_config()["task_always_eager"] is False
    assert celery_app.conf.task_always_eager is False
    assert celery_app.conf.task_acks_late is True
    routes = celery_app.conf.task_routes
    assert routes["app.workers.tasks.generate_export_job"]["queue"] == get_settings().export_queue_name


def test_readiness_reports_queue_and_redis_without_urls(client):
    body = client.get("/ready").json()
    assert body["queue"] in {"in_memory", "ok", "unconfigured", "unavailable"}
    assert "redis" in body
    assert "memory://" not in str(body) and "redis://" not in str(body)


def test_ops_status_reports_export_failures_and_worker_state(client):
    headers = auth_header(login(client, "admin.user"))
    body = client.get("/ops/status", headers=headers).json()
    assert set(body["export_jobs"]) == {"by_status", "failed_permanently"}
    assert body["workers"]["status"] in {"not_used", "no_workers", "ok", "unavailable", "not_installed"}
    assert "redis://" not in str(body)


# ---------------------------------------------------------------------------
# Database connection policy (work package P)
# ---------------------------------------------------------------------------


def test_managed_database_must_use_tls_unless_explicitly_exempted():
    assert validate_runtime_settings(_production(db_sslmode="require")) == []
    assert any(
        "DB_SSLMODE" in error for error in validate_runtime_settings(_production(db_sslmode=""))
    )
    # A private network you control can opt out, but only by saying so.
    assert validate_runtime_settings(_production(db_sslmode="", db_require_ssl=False)) == []
    in_url = _production(
        db_sslmode="",
        database_url="postgresql+psycopg://hpip:owner@db:5432/hpip?sslmode=require",
    )
    assert validate_runtime_settings(in_url) == []
    assert any(
        "disables TLS" in error
        for error in validate_runtime_settings(
            _production(database_url="postgresql+psycopg://hpip:owner@db:5432/hpip?sslmode=disable")
        )
    )


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"database_url": "sqlite+pysqlite:///./hpip.db"}, "must be PostgreSQL"),
        ({"database_url": "not-a-url"}, "malformed"),
        ({"database_url": "mysql://hpip:owner@db:3306/hpip"}, "PostgreSQL driver"),
        ({"migration_database_url": "mysql://hpip:owner@db:3306/hpip"}, "MIGRATION_DATABASE_URL"),
        ({"migration_database_url": "postgresql+psycopg://hpip:change-me@db:5432/hpip"}, "placeholder"),
        ({"db_pool_size": 20, "db_max_overflow": 20}, "too large"),
    ],
)
def test_production_rejects_unsafe_database_configuration(overrides, expected):
    errors = validate_runtime_settings(_production(**overrides))
    assert any(expected in error for error in errors), errors


def test_migration_url_prefers_the_direct_connection():
    from app.db.session import migration_url

    pooled = _production(database_url="postgresql+psycopg://hpip:owner@pooler:5432/hpip")
    assert migration_url(pooled) == "postgresql+psycopg://hpip:owner@pooler:5432/hpip"
    direct = _production(
        database_url="postgresql+psycopg://hpip:owner@pooler:5432/hpip",
        migration_database_url="postgresql+psycopg://hpip:owner@direct:5432/hpip",
    )
    assert migration_url(direct) == "postgresql+psycopg://hpip:owner@direct:5432/hpip"


def test_engine_uses_a_small_pool_and_passes_tls_settings():
    from app.db.session import create_db_engine

    settings = _production(db_sslmode="require", db_pool_size=3, db_max_overflow=2)
    engine = create_db_engine(settings)
    try:
        assert engine.pool.size() == 3
        assert engine.pool._max_overflow == 2
        assert engine.dialect.name == "postgresql"
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# DHIS2 stays inert (work package S)
# ---------------------------------------------------------------------------


def test_dhis2_is_disabled_by_default_and_reported_separately():
    from app.integrations.dhis2 import dhis2_readiness_status

    settings = Settings(_env_file=None)
    assert settings.dhis2_enabled is False and settings.sync_enabled is False
    assert validate_runtime_settings(_production()) == []
    assert dhis2_readiness_status() == "disabled"


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"sync_enabled": True}, "SYNC_ENABLED requires DHIS2_ENABLED"),
        ({"dhis2_enabled": True, "dhis2_base_url": ""}, "DHIS2_BASE_URL is required"),
        (
            {"dhis2_enabled": True, "dhis2_base_url": "http://hmis.health.go.ug"},
            "must be HTTPS",
        ),
        (
            {"dhis2_enabled": True, "dhis2_base_url": "https://hmis.health.go.ug"},
            "requires DHIS2_USERNAME",
        ),
        (
            {
                "dhis2_enabled": True,
                "dhis2_base_url": "https://hmis.health.go.ug",
                "dhis2_auth_method": "pat",
            },
            "requires DHIS2_PAT",
        ),
    ],
)
def test_enabling_dhis2_without_complete_configuration_fails_closed(overrides, expected):
    errors = validate_runtime_settings(_production(**overrides))
    assert any(expected in error for error in errors), errors


def test_base64_dhis2_password_transport_decodes_and_invalid_input_fails_closed():
    password = "arbitrary ${ROTATED} # secret"
    encoded = base64.b64encode(password.encode("utf-8")).decode("ascii")
    configured = _production(
        dhis2_enabled=True,
        dhis2_base_url="https://hmis.health.go.ug",
        dhis2_username="authorised.user",
        dhis2_password_b64=encoded,
    )
    assert configured.effective_dhis2_password == password
    assert not [error for error in validate_runtime_settings(configured) if "DHIS2" in error]

    invalid = _production(
        dhis2_enabled=True,
        dhis2_base_url="https://hmis.health.go.ug",
        dhis2_username="authorised.user",
        dhis2_password_b64="not-valid-base64!",
    )
    assert "DHIS2_PASSWORD_B64 is invalid." in validate_runtime_settings(invalid)


def test_prepared_dhis2_commands_contact_nothing_while_disabled(monkeypatch, capsys):
    import json as json_module

    from scripts import dhis2_discovery, dhis2_refresh

    monkeypatch.setattr(get_settings(), "dhis2_enabled", False)
    monkeypatch.setattr(get_settings(), "sync_enabled", False)

    assert dhis2_refresh.main(["--scheduled", "--json"]) == 0
    refresh = json_module.loads(capsys.readouterr().out)
    assert refresh["mode"] == "inert"
    assert refresh["continuous_polling"] is False
    assert refresh["closed_periods_refreshed"] is False
    assert "DHIS2_ENABLED is false." in refresh["blocked_reasons"]

    assert dhis2_discovery.main(["--resource", "org-units"]) == 3
    discovery = json_module.loads(capsys.readouterr().out)
    assert discovery["mode"] == "blocked"
    assert discovery["http_methods"] == ["GET"]
    assert discovery["credentials_in_output"] is False
    assert discovery["page_size"] <= get_settings().dhis2_page_size


def test_enabled_refresh_enqueues_only_mapped_recent_periods(session, monkeypatch, capsys):
    import json as json_module

    from app.models import OrgUnitMapping, Programme, SourceMapping, SyncJob
    from scripts import dhis2_refresh

    settings = get_settings()
    monkeypatch.setattr(settings, "dhis2_enabled", True)
    monkeypatch.setattr(settings, "sync_enabled", True)
    monkeypatch.setattr(settings, "dhis2_base_url", "https://hmis.health.go.ug")
    monkeypatch.setattr(settings, "dhis2_username", "configured-user")
    monkeypatch.setattr(settings, "dhis2_password", "configured-secret")
    programme = session.scalar(select(Programme).where(Programme.code == "MNCH"))
    root = session.scalar(select(OrgUnit).where(OrgUnit.code == "UG"))
    # The scheduler now requires the mapping set to cover every source key the programme's
    # formulas depend on, so mapping ANC1 alone would (correctly) block the refresh.
    from app.services.mapping_coverage import required_source_keys

    for index, source_key in enumerate(sorted(required_source_keys("MNCH"))):
        session.add(
            SourceMapping(
                internal_source_key=source_key,
                programme_id=programme.id,
                dhis2_item_uid=f"APPROVED_UID_{index}",
                mapping_version="approved-v1",
                enabled=True,
            )
        )
    session.add(OrgUnitMapping(org_unit_id=root.id, source_system="dhis2", external_uid="APPROVED_UG_UID"))
    session.commit()
    dispatched = []
    monkeypatch.setattr(dhis2_refresh, "get_session_factory", lambda: lambda: session)
    monkeypatch.setattr(dhis2_refresh, "should_run_eager", lambda: False)
    monkeypatch.setattr(dhis2_refresh, "dispatch_sync_job", lambda job_id: dispatched.append(job_id))

    assert dhis2_refresh.main(["--scheduled", "--json"]) == 0

    report = json_module.loads(capsys.readouterr().out)
    jobs = list(session.scalars(select(SyncJob)).all())
    assert report["mode"] == "executed"
    assert report["closed_periods_refreshed"] is False
    assert report["job_count"] == len(dhis2_refresh._recent_periods(datetime.now(UTC).date()))
    assert len(dispatched) == len(jobs) == report["job_count"]
    assert {job.programme_id for job in jobs} == {programme.id}
    assert {job.mapping_version for job in jobs} == {"approved-v1"}

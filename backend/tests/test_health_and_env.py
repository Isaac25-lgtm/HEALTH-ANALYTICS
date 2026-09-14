from app.config import Settings, validate_runtime_settings


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["phase"] == "phase-7-corrective"


def test_ready(client):
    response = client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["database"] == "ok"
    assert body["dhis2"] in {"not_configured", "configured_unverified"}
    assert body["status"] in {"ok", "degraded"}


def test_production_rejects_sqlite_and_dev_seed():
    settings = Settings(
        app_env="production",
        database_url="sqlite+pysqlite:///./x.db",
        auth_secret="replace-with-a-long-random-development-secret-at-least-32-chars",
        seed_dev_data=True,
        seed_password="dev-only-change-me",
    )
    errors = validate_runtime_settings(settings)
    assert any("PostgreSQL" in error for error in errors)
    assert any("SEED_DEV_DATA" in error for error in errors)
    assert any("AUTH_SECRET" in error for error in errors)


def test_development_placeholder_secret_is_allowed():
    settings = Settings(
        app_env="development",
        database_url="sqlite+pysqlite:///:memory:",
        auth_secret="replace-with-a-long-random-development-secret-at-least-32-chars",
        seed_dev_data=True,
    )
    assert validate_runtime_settings(settings) == []

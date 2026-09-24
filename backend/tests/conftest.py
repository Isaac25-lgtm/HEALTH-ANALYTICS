import os

os.environ.setdefault(
    "AUTH_SECRET", "test-secret-value-that-is-32-chars-min"
)
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("SEED_DEV_DATA", "false")
# A developer's gitignored live-DHIS2 .env must never make the automated suite contact the
# network or change default-gate assertions. Individual connector tests opt in with mocks.
os.environ.setdefault("DHIS2_ENABLED", "false")
os.environ.setdefault("SYNC_ENABLED", "false")
os.environ.setdefault("DHIS2_LOGIN_ENABLED", "false")
# Owner approvals and history windows recorded in a local operator .env are live-instance facts;
# tests assert the unapproved defaults and set approvals explicitly where they need them.
os.environ.setdefault("BOUNDARY_DISTRICT_HIERARCHY_APPROVAL_REFERENCE", "")
os.environ.setdefault("BOUNDARY_SUB_COUNTY_HIERARCHY_APPROVAL_REFERENCE", "")
os.environ.setdefault("RAW_AGGREGATE_RETENTION_DAYS", "7")
os.environ.setdefault("CALCULATION_SNAPSHOT_RETENTION_MONTHS", "36")
# Explicit test-only gates. Production defaults are queue execution and Redis rate limiting.
os.environ.setdefault("EXPORT_EAGER", "true")
os.environ.setdefault("RATE_LIMIT_BACKEND", "memory")
# Real Celery publishing over kombu's in-process transport; no network broker is contacted.
os.environ.setdefault("CELERY_BROKER_URL", "memory://")
os.environ.setdefault("CELERY_RESULT_BACKEND", "cache+memory://")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.services.rate_limit import reset_rate_limits
from app.services.seed import seed_reference_data

get_settings.cache_clear()

SEED_PASSWORD = "dev-only-change-me"


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    reset_rate_limits()
    yield
    reset_rate_limits()


@pytest.fixture()
def engine():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def session(engine) -> Session:
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    db = factory()
    seed_reference_data(db, SEED_PASSWORD)
    db.commit()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def client(session: Session) -> TestClient:
    def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def login(client: TestClient, username: str, password: str = SEED_PASSWORD) -> str:
    response = client.post("/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    body = response.json()
    assert "access_token" not in body
    return body["csrf_token"]


def auth_header(csrf_token: str) -> dict[str, str]:
    return {"X-CSRF-Token": csrf_token}


def query_dashboard(client: TestClient, headers: dict[str, str], org_unit_id, **fields):
    """Execute the analytical dashboard through the CSRF-protected POST contract."""
    body = {"org_unit_id": str(org_unit_id), "period": "FY2024/25", "module": "anc"}
    body.update({key: value for key, value in fields.items() if value is not None})
    return client.post("/analytics/dashboard/query", json=body, headers=headers)


def query_module(client: TestClient, headers: dict[str, str], module: str, org_unit_id, **fields):
    body = {"org_unit_id": str(org_unit_id), "period": "FY2024/25"}
    body.update({key: value for key, value in fields.items() if value is not None})
    return client.post(f"/analytics/modules/{module}/query", json=body, headers=headers)


def download_export(client: TestClient, headers: dict[str, str], job_id: str):
    return client.post(f"/exports/jobs/{job_id}/download", headers=headers)


def pytest_sessionfinish(session, exitstatus):
    """With HPIP_FAIL_ON_SKIP=1 (CI) any skipped test fails the run.

    PostgreSQL and Redis tests skip locally when no disposable service is configured. In CI
    those services exist, so a skip means the verification silently did not happen.
    """
    if os.environ.get("HPIP_FAIL_ON_SKIP") != "1":
        return
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    skipped = list(reporter.stats.get("skipped", [])) if reporter else []
    if not skipped:
        return
    reporter.write_line(f"HPIP_FAIL_ON_SKIP=1: {len(skipped)} test(s) skipped; failing the run.", red=True)
    for report in skipped:
        reason = report.longrepr[-1] if isinstance(report.longrepr, tuple) else report.longrepr
        reporter.write_line(f"  skipped {report.nodeid}: {reason}", red=True)
    session.exitstatus = pytest.ExitCode.TESTS_FAILED

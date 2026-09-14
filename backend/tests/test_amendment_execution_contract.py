"""Amendment §1: analytical execution is a CSRF-protected POST; GET never mutates."""

import hashlib
import re
from uuid import UUID, uuid4

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.db.base import Base
from app.db.session import create_db_engine, reset_engine
from app.main import app
from app.models import (
    AnalysisSnapshot,
    CalculatedValue,
    CalculationRun,
    DataQualityFlag,
    OrgUnit,
    Programme,
    User,
    UserProgrammeScope,
)
from app.services.seed import seed_reference_data
from tests.conftest import SEED_PASSWORD, auth_header, login, query_dashboard, query_module
from tests.helpers import put_population, put_raw


def _unit(session, code):
    return session.scalar(select(OrgUnit).where(OrgUnit.code == code))


def _count(session, model) -> int:
    return session.scalar(select(func.count()).select_from(model))


@pytest.fixture()
def real_db(tmp_path, monkeypatch):
    """A file database reached through the production get_db dependency (no override)."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'contract.db'}")
    get_settings.cache_clear()
    reset_engine()
    engine = create_db_engine()
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    seed = factory()
    seed_reference_data(seed, SEED_PASSWORD)
    pader = seed.scalar(select(OrgUnit).where(OrgUnit.code == "PADER"))
    put_population(seed, pader, 2024, 1_000_000, code="CONTRACT_POP")
    put_raw(seed, pader, "FY2024/25", "ANC1", 40_000)
    seed.commit()
    seed.close()
    app.dependency_overrides.clear()
    try:
        yield engine, factory
    finally:
        engine.dispose()
        get_settings.cache_clear()
        reset_engine()


def _database_digest(engine) -> str:
    digest = hashlib.sha256()
    with engine.connect() as conn:
        for table in Base.metadata.sorted_tables:
            rows = sorted(repr(tuple(row)) for row in conn.execute(select(table)).all())
            digest.update(table.name.encode())
            for row in rows:
                digest.update(row.encode())
    return digest.hexdigest()


def _pader_id(factory) -> UUID:
    with factory() as session:
        return session.scalar(select(OrgUnit.id).where(OrgUnit.code == "PADER"))


def test_every_get_route_leaves_the_database_unchanged(real_db):
    engine, factory = real_db
    pader_id = _pader_id(factory)
    with TestClient(app, raise_server_exceptions=False) as client:
        headers = auth_header(login(client, "admin.user"))
        dash = query_dashboard(client, headers, pader_id)
        assert dash.status_code == 201, dash.text
        snapshot = dash.json()
        export = client.post(
            "/exports/excel",
            json={
                "org_unit_id": str(pader_id),
                "period": "FY2024/25",
                "module": "anc",
                "analysis_snapshot_id": snapshot["analysis_snapshot_id"],
                "view_hash": snapshot["view_hash"],
            },
            headers=headers,
        )
        assert export.status_code == 202, export.text
        known = {
            "snapshot_id": snapshot["analysis_snapshot_id"],
            "job_id": export.json()["job_id"],
            "run_id": snapshot["module_result"]["current_run_id"],
            "org_unit_id": str(pader_id),
        }
        query = {"org_unit_id": str(pader_id), "period": "FY2024/25", "module": "anc", "programme": "MNCH"}
        before = _database_digest(engine)
        exercised = []
        for route in app.routes:
            if not isinstance(route, APIRoute) or "GET" not in route.methods:
                continue
            path = re.sub(r"\{(\w+)\}", lambda match: known.get(match.group(1), str(uuid4())), route.path)
            response = client.get(path, params=query, headers=headers)
            exercised.append((route.path, response.status_code))
        after = _database_digest(engine)
    assert len(exercised) >= 20
    assert before == after, exercised


def test_legacy_mutating_get_routes_are_removed(client, session):
    pader = _unit(session, "PADER")
    csrf = login(client, "pader.focal")
    runs, snapshots = _count(session, CalculationRun), _count(session, AnalysisSnapshot)
    for path in (
        f"/analytics/dashboard?org_unit_id={pader.id}&period=FY2024/25&module=anc",
        f"/analytics/modules/anc?org_unit_id={pader.id}&period=FY2024/25",
        f"/exports/jobs/{uuid4()}/file",
    ):
        response = client.get(path, headers=auth_header(csrf))
        assert response.status_code in {404, 405}, path
    assert _count(session, CalculationRun) == runs
    assert _count(session, AnalysisSnapshot) == snapshots


def test_analytical_posts_require_csrf(client, session):
    pader = _unit(session, "PADER")
    login(client, "pader.focal")
    runs = _count(session, CalculationRun)
    body = {"org_unit_id": str(pader.id), "period": "FY2024/25", "module": "anc"}
    dashboard = client.post("/analytics/dashboard/query", json=body)
    module = client.post("/analytics/modules/anc/query", json={"org_unit_id": str(pader.id), "period": "FY2024/25"})
    download = client.post(f"/exports/jobs/{uuid4()}/download")
    forged = client.post("/analytics/dashboard/query", json=body, headers={"X-CSRF-Token": "forged-token-value"})
    for response in (dashboard, module, download, forged):
        assert response.status_code == 403
        assert response.json()["code"] == "csrf_failed"
    assert _count(session, CalculationRun) == runs


def test_request_key_reuse_returns_the_committed_snapshot_without_new_runs(client, session):
    pader = _unit(session, "PADER")
    put_population(session, pader, 2024, 1_000_000, code="REUSE_POP")
    put_raw(session, pader, "FY2024/25", "ANC1", 40_000)
    session.commit()
    headers = auth_header(login(client, "pader.focal"))
    first = query_dashboard(client, headers, pader.id, request_key="refresh-key-0001")
    assert first.status_code == 201, first.text
    assert first.json()["snapshot_reused"] is False
    runs, snapshots, values = (
        _count(session, CalculationRun),
        _count(session, AnalysisSnapshot),
        _count(session, CalculatedValue),
    )
    repeat = query_dashboard(client, headers, pader.id, request_key="refresh-key-0001")
    assert repeat.status_code == 200, repeat.text
    body = repeat.json()
    assert body["snapshot_reused"] is True
    assert body["analysis_snapshot_id"] == first.json()["analysis_snapshot_id"]
    assert body["view_hash"] == first.json()["view_hash"]
    assert body["module_result"]["current_run_id"] == first.json()["module_result"]["current_run_id"]
    assert _count(session, CalculationRun) == runs
    assert _count(session, AnalysisSnapshot) == snapshots
    assert _count(session, CalculatedValue) == values


def test_request_key_reused_for_a_different_request_conflicts(client, session):
    pader = _unit(session, "PADER")
    headers = auth_header(login(client, "pader.focal"))
    assert query_dashboard(client, headers, pader.id, request_key="conflict-key-01").status_code == 201
    snapshots = _count(session, AnalysisSnapshot)
    conflict = query_dashboard(client, headers, pader.id, request_key="conflict-key-01", period="FY2023/24")
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "snapshot_conflict"
    assert _count(session, AnalysisSnapshot) == snapshots


def test_request_keys_are_scoped_to_their_user(client, session):
    acholi = _unit(session, "ACHOLI")
    first = query_dashboard(
        client, auth_header(login(client, "acholi.analyst")), acholi.id, request_key="shared-key-001"
    )
    assert first.status_code == 201
    second = query_dashboard(
        client, auth_header(login(client, "national.analyst")), acholi.id, request_key="shared-key-001"
    )
    assert second.status_code == 201
    assert second.json()["analysis_snapshot_id"] != first.json()["analysis_snapshot_id"]


def test_snapshot_get_is_read_only_and_owner_scoped(client, session):
    pader = _unit(session, "PADER")
    headers = auth_header(login(client, "pader.focal"))
    created = query_dashboard(client, headers, pader.id).json()
    runs, snapshots, flags = (
        _count(session, CalculationRun),
        _count(session, AnalysisSnapshot),
        _count(session, DataQualityFlag),
    )
    fetched = client.get(f"/analysis-snapshots/{created['analysis_snapshot_id']}", headers=headers)
    assert fetched.status_code == 200
    body = fetched.json()
    assert body["analysis_snapshot_id"] == created["analysis_snapshot_id"]
    assert body["view_hash"] == created["view_hash"]
    assert body["module_result"] == created["module_result"]
    assert (_count(session, CalculationRun), _count(session, AnalysisSnapshot)) == (runs, snapshots)
    assert _count(session, DataQualityFlag) == flags
    other = client.get(
        f"/analysis-snapshots/{created['analysis_snapshot_id']}",
        headers=auth_header(login(client, "national.analyst")),
    )
    assert other.status_code == 404


def test_snapshot_access_is_rechecked_and_ai_cannot_omit_the_module(client, session):
    acholi = _unit(session, "ACHOLI")
    headers = auth_header(login(client, "acholi.analyst"))
    created = query_dashboard(client, headers, acholi.id, module="mpdsr")
    assert created.status_code == 201, created.text
    snapshot = created.json()
    analyst = session.scalar(select(User).where(User.username == "acholi.analyst"))
    mpdsr = session.scalar(select(Programme).where(Programme.code == "MPDSR"))
    session.execute(
        delete(UserProgrammeScope).where(
            UserProgrammeScope.user_id == analyst.id,
            UserProgrammeScope.programme_id == mpdsr.id,
        )
    )
    session.commit()
    session.expire_all()
    fetched = client.get(f"/analysis-snapshots/{snapshot['analysis_snapshot_id']}", headers=headers)
    assert fetched.status_code == 403
    bypass = client.post(
        "/ai/findings",
        json={
            "org_unit_id": str(acholi.id),
            "period": "FY2024/25",
            "analysis_snapshot_id": snapshot["analysis_snapshot_id"],
            "view_hash": snapshot["view_hash"],
        },
        headers=headers,
    )
    assert bypass.status_code == 403


def test_committed_ids_exist_in_a_new_session(real_db):
    engine, factory = real_db
    pader_id = _pader_id(factory)
    with TestClient(app) as client:
        headers = auth_header(login(client, "pader.focal"))
        dash = query_dashboard(client, headers, pader_id, request_key="persist-key-001")
        assert dash.status_code == 201, dash.text
        module = query_module(client, headers, "anc", pader_id)
        assert module.status_code == 201, module.text
    snapshot_id = UUID(dash.json()["analysis_snapshot_id"])
    run_id = UUID(dash.json()["module_result"]["current_run_id"])
    module_run_id = UUID(module.json()["current_run_id"])
    with factory() as other:
        stored = other.get(AnalysisSnapshot, snapshot_id)
        assert stored is not None
        assert stored.idempotency_key == "persist-key-001"
        assert stored.payload_json["analysis_snapshot_id"] == str(snapshot_id)
        assert other.get(CalculationRun, run_id) is not None
        assert other.get(CalculationRun, module_run_id) is not None
        assert other.scalars(select(CalculatedValue).where(CalculatedValue.calculation_run_id == run_id)).first()
    with TestClient(app) as fresh:
        headers = auth_header(login(fresh, "pader.focal"))
        again = fresh.get(f"/analysis-snapshots/{snapshot_id}", headers=headers)
        assert again.status_code == 200
        assert again.json()["module_result"]["current_run_id"] == str(run_id)


def test_failed_module_execution_leaves_no_partial_runs(real_db, monkeypatch):
    engine, factory = real_db
    pader_id = _pader_id(factory)

    def boom(*_args, **_kwargs):
        raise RuntimeError("forced failure after calculation runs were flushed")

    monkeypatch.setattr("app.services.modules._freshness", boom)
    with TestClient(app, raise_server_exceptions=False) as client:
        headers = auth_header(login(client, "pader.focal"))
        module = query_module(client, headers, "anc", pader_id)
        dashboard = query_dashboard(client, headers, pader_id)
    assert module.status_code >= 500
    assert dashboard.status_code >= 500
    with factory() as other:
        assert _count(other, CalculationRun) == 0
        assert _count(other, CalculatedValue) == 0
        assert _count(other, AnalysisSnapshot) == 0
        assert _count(other, DataQualityFlag) == 0

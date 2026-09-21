from sqlalchemy import select

from app.domain.enums import ConnectorType, JobStatus
from app.models import OrgUnit, Programme, SyncJob, User
from app.services.sync import claim_sync_job
from tests.conftest import auth_header, login


def _unit(session, code: str) -> OrgUnit:
    return session.scalar(select(OrgUnit).where(OrgUnit.code == code))


def test_system_administrator_context_is_national_and_complete(client):
    csrf = login(client, "admin.user")
    body = client.get("/me/context", headers=auth_header(csrf)).json()
    assert body["landing_org_unit"]["code"] == "UG"
    assert set(body["programmes"]) == {"MNCH", "EPI", "MPDSR"}
    assert body["available_geography_levels"]
    assert {row["level_type"] for row in body["geography_entry_units"]} == set(
        body["available_geography_levels"]
    )


def test_dashboard_refresh_fails_before_queue_without_complete_mapping(client, session, monkeypatch):
    import app.api.routes.sync as sync_routes

    enabled = sync_routes.get_settings().model_copy(
        update={"dhis2_enabled": True, "sync_enabled": True}
    )
    monkeypatch.setattr(sync_routes, "get_settings", lambda: enabled)
    csrf = login(client, "admin.user")
    response = client.post(
        "/sync/refresh",
        json={
            "org_unit_id": str(_unit(session, "UG").id),
            "period": "FY2024/25",
            "module": "anc",
            "idempotency_key": "refresh-test-0001",
        },
        headers=auth_header(csrf),
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "mapping_coverage_incomplete"
    assert session.scalar(select(SyncJob)) is None


def test_sync_claim_is_atomic_and_cancel_endpoint_is_scoped(client, session):
    admin = session.scalar(select(User).where(User.username == "admin.user"))
    programme = session.scalar(select(Programme).where(Programme.code == "MNCH"))
    job = SyncJob(
        job_type=ConnectorType.AGGREGATE.value,
        status=JobStatus.QUEUED.value,
        org_unit_id=_unit(session, "UG").id,
        programme_id=programme.id,
        initiated_by_user_id=admin.id,
    )
    session.add(job)
    session.commit()
    assert claim_sync_job(session, job.id) is True
    assert claim_sync_job(session, job.id) is False
    # A redelivered task may reclaim a row left running only after the worker has acquired the
    # per-job execution lock. Production uses a PostgreSQL advisory lock; the explicit argument
    # represents that precondition here.
    assert claim_sync_job(session, job.id, reclaim_running=True) is True

    queued = SyncJob(
        job_type=ConnectorType.AGGREGATE.value,
        status=JobStatus.QUEUED.value,
        org_unit_id=_unit(session, "UG").id,
        programme_id=programme.id,
        initiated_by_user_id=admin.id,
    )
    session.add(queued)
    session.commit()
    csrf = login(client, "admin.user")
    response = client.post(f"/sync/jobs/{queued.id}/cancel", headers=auth_header(csrf))
    assert response.status_code == 202
    assert response.json()["status"] == JobStatus.CANCELLED.value
    assert session.get(SyncJob, queued.id).cancelled is True


def test_empty_snapshot_cannot_be_exported(client, session):
    csrf = login(client, "admin.user")
    uganda = _unit(session, "UG")
    dashboard = client.post(
        "/analytics/dashboard/query",
        json={
            "org_unit_id": str(uganda.id),
            "period": "FY2024/25",
            "module": "anc",
            "request_key": "empty-export-test",
        },
        headers=auth_header(csrf),
    )
    assert dashboard.status_code == 201, dashboard.text
    payload = dashboard.json()
    assert payload["exports"]["actions"][0]["available"] is False
    response = client.post(
        "/exports/excel",
        json={
            "org_unit_id": str(uganda.id),
            "period": "FY2024/25",
            "module": "anc",
            "analysis_snapshot_id": payload["analysis_snapshot_id"],
            "view_hash": payload["view_hash"],
        },
        headers=auth_header(csrf),
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "export_no_verified_data"

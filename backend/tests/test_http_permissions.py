from sqlalchemy import select

from app.models import AuditLog, OrgUnit
from tests.conftest import auth_header, login


def test_unauthenticated_me_context(client):
    response = client.get("/me/context")
    assert response.status_code == 401


def test_national_context(client):
    token = login(client, "national.analyst")
    response = client.get("/me/context", headers=auth_header(token))
    assert response.status_code == 200
    body = response.json()
    assert body["landing_org_unit"]["code"] == "UG"
    assert "MNCH" in body["programmes"]
    assert "export" in body["actions"]


def test_facility_context(client):
    token = login(client, "paderhc3.user")
    response = client.get("/me/context", headers=auth_header(token))
    assert response.status_code == 200
    assert response.json()["landing_org_unit"]["code"] == "PADER_HC_III"


def test_url_tamper_does_not_bypass_geography(client, session):
    token = login(client, "pader.focal")
    teso = session.scalar(select(OrgUnit).where(OrgUnit.code == "TESO"))
    response = client.get(f"/org-units/{teso.id}", headers=auth_header(token))
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "forbidden_geography"


def test_children_are_scope_filtered(client, session):
    token = login(client, "acholi.analyst")
    uganda = session.scalar(select(OrgUnit).where(OrgUnit.code == "UG"))
    denied = client.get(f"/org-units/{uganda.id}/children", headers=auth_header(token))
    assert denied.status_code == 403
    acholi = session.scalar(select(OrgUnit).where(OrgUnit.code == "ACHOLI"))
    allowed = client.get(f"/org-units/{acholi.id}/children", headers=auth_header(token))
    assert allowed.status_code == 200
    codes = {row["code"] for row in allowed.json()}
    assert codes == {"PADER", "KITGUM"}


def test_view_only_cannot_call_export(client, session):
    token = login(client, "view.only")
    uganda = session.scalar(select(OrgUnit).where(OrgUnit.code == "UG"))
    response = client.post(
        f"/exports/excel?org_unit_id={uganda.id}&programme=MNCH",
        headers=auth_header(token),
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "forbidden_action"


def test_mnch_only_cannot_request_epi_export(client, session):
    token = login(client, "mnch.only")
    uganda = session.scalar(select(OrgUnit).where(OrgUnit.code == "UG"))
    response = client.post(
        f"/exports/excel?org_unit_id={uganda.id}&programme=EPI",
        headers=auth_header(token),
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "forbidden_programme"


def test_programmes_are_filtered(client):
    token = login(client, "mnch.only")
    response = client.get("/programmes", headers=auth_header(token))
    assert response.status_code == 200
    assert [row["code"] for row in response.json()] == ["MNCH"]


def test_ordinary_mnch_user_cannot_read_mpdsr_events(client):
    token = login(client, "national.analyst")
    response = client.get("/mpdsr/events", headers=auth_header(token))
    assert response.status_code == 403


def test_mpdsr_analyst_events_are_empty_envelope(client):
    token = login(client, "mpdsr.analyst")
    response = client.get("/mpdsr/events", headers=auth_header(token))
    assert response.status_code == 200
    assert response.json()["events"] == []


def test_mpdsr_linelist_requires_sensitive_permission(client, session):
    token = login(client, "mpdsr.analyst")
    acholi = session.scalar(select(OrgUnit).where(OrgUnit.code == "ACHOLI"))
    response = client.post(
        f"/exports/mpdsr-linelist?org_unit_id={acholi.id}",
        headers=auth_header(token),
    )
    assert response.status_code == 403


def test_admin_probe_writes_audit_log(client, session):
    token = login(client, "admin.user")
    response = client.post("/admin/probe", headers=auth_header(token))
    assert response.status_code == 200
    entry = session.scalar(select(AuditLog).where(AuditLog.action == "admin_probe"))
    assert entry is not None
    assert entry.resource_type == "admin"


def test_non_admin_cannot_probe(client):
    token = login(client, "national.analyst")
    response = client.post("/admin/probe", headers=auth_header(token))
    assert response.status_code == 403

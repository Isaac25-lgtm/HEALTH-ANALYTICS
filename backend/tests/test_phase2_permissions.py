from sqlalchemy import select

from app.models import OrgUnit
from tests.conftest import auth_header, login


def test_facility_user_cannot_query_parent(client, session):
    token = login(client, "paderhc3.user")
    pader = session.scalar(select(OrgUnit).where(OrgUnit.code == "PADER"))
    response = client.get(f"/org-units/{pader.id}", headers=auth_header(token))
    assert response.status_code == 403


def test_district_cannot_query_sibling(client, session):
    token = login(client, "pader.focal")
    kitgum = session.scalar(select(OrgUnit).where(OrgUnit.code == "KITGUM"))
    response = client.get(f"/populations/resolve?org_unit_id={kitgum.id}&period=FY2024/25", headers=auth_header(token))
    assert response.status_code == 403


def test_national_can_query_descendant(client, session):
    token = login(client, "national.analyst")
    hc3 = session.scalar(select(OrgUnit).where(OrgUnit.code == "PADER_HC_III"))
    response = client.get(f"/org-units/{hc3.id}/ancestors", headers=auth_header(token))
    assert response.status_code == 200
    assert any(row["code"] == "UG" for row in response.json())


def test_view_only_cannot_sync_or_see_mappings(client, session):
    token = login(client, "view.only")
    uganda = session.scalar(select(OrgUnit).where(OrgUnit.code == "UG"))
    denied = client.post(
        "/sync/jobs",
        json={
            "org_unit_id": str(uganda.id),
            "period": "202407",
            "programme": "MNCH",
            "job_type": "aggregate",
        },
        headers=auth_header(token),
    )
    assert denied.status_code == 403
    mappings = client.get("/mappings", headers=auth_header(token))
    assert mappings.status_code == 403


def test_mnch_only_cannot_list_epi_indicators(client):
    token = login(client, "mnch.only")
    response = client.get("/indicators", headers=auth_header(token))
    assert response.status_code == 200
    codes = {row["code"] for row in response.json()}
    assert "ANC1_COVERAGE" in codes
    assert "MV4_COVERAGE" not in codes


def test_ordinary_user_quality_flag_hides_event_uid(client, session):
    token = login(client, "national.analyst")
    response = client.get("/quality/flags", headers=auth_header(token))
    assert response.status_code == 200
    for row in response.json():
        assert row.get("event_uid") in {None, ""}


def test_mpdsr_events_still_require_sensitive_permission(client):
    token = login(client, "national.analyst")
    response = client.get("/mpdsr/events", headers=auth_header(token))
    assert response.status_code == 403

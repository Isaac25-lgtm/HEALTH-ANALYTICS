from sqlalchemy import select

from app.models import OrgUnit, User
from tests.conftest import auth_header, login, query_dashboard
from tests.helpers import put_population, put_raw


def _unit(session, code):
    return session.scalar(select(OrgUnit).where(OrgUnit.code == code))


def _user(session, username):
    return session.scalar(select(User).where(User.username == username))


def test_national_dashboard_is_permission_safe(client, session):
    uganda = _unit(session, "UG")
    csrf = login(client, "national.analyst")
    response = query_dashboard(client, auth_header(csrf), uganda.id)
    assert response.status_code == 201
    body = response.json()
    assert body["screen"] == "national"
    assert body["module"] == "anc"
    assert body["geometry"]["mapping_state"] == "boundaries_awaiting_approved_mapping"
    assert body["exports"]["phase6_implemented"] is True
    denied = login(client, "acholi.analyst")
    blocked = query_dashboard(client, auth_header(denied), uganda.id)
    assert blocked.status_code == 403


def test_regional_and_district_facility_screens(client, session):
    acholi = _unit(session, "ACHOLI")
    pader = _unit(session, "PADER")
    csrf = login(client, "acholi.analyst")
    regional = query_dashboard(client, auth_header(csrf), acholi.id)
    assert regional.status_code == 201
    assert regional.json()["screen"] == "regional"
    district = query_dashboard(client, auth_header(csrf), pader.id)
    assert district.status_code == 201
    body = district.json()
    assert body["screen"] == "district"
    assert body["module_result"]["comparison_grain"] == "facility"
    assert any(row["org_unit_code"] == "PADER_HC_III" for row in body["facility_scorecard"])


def test_facility_missing_population_and_service_values(client, session):
    facility = _unit(session, "PADER_HC_III")
    put_raw(session, facility, "FY2024/25", "ANC1", 10)
    put_raw(session, facility, "FY2024/25", "ANC1_FT", 0)
    session.commit()
    csrf = login(client, "paderhc3.user")
    response = query_dashboard(client, auth_header(csrf), facility.id)
    assert response.status_code == 201
    body = response.json()
    assert body["screen"] == "facility"
    assert body["population"]["status"] == "unavailable"
    assert body["population"]["population"] is None
    by_code = {row["indicator_code"]: row for row in body["module_result"]["indicators"]}
    assert by_code["ANC1_COVERAGE"]["raw_value"] is None
    assert by_code["ANC1_FIRST_TRIMESTER"]["raw_value"] == 0
    assert any(item["code"] == "missing_population" for item in body["insights"])


def test_mnch_user_cannot_open_mpdsr_dashboard(client, session):
    uganda = _unit(session, "UG")
    csrf = login(client, "mnch.only")
    response = query_dashboard(client, auth_header(csrf), uganda.id, module="mpdsr")
    assert response.status_code == 403


def test_mortality_is_not_ranked(client, session):
    pader = _unit(session, "PADER")
    csrf = login(client, "pader.focal")
    response = query_dashboard(
        client, auth_header(csrf), pader.id, module="intrapartum", selected_indicator="PMR"
    )
    assert response.status_code == 201
    ranking = response.json()["ranking"]
    assert ranking["ranking_allowed"] is False
    assert ranking["top"] == []
    assert ranking["best"] == []
    assert ranking["worst"] == []


def test_over_100_retained_on_dashboard(session, client):
    acholi = _unit(session, "ACHOLI")
    put_population(session, acholi, 2024, 1_000_000, code="DASH_POP_2024")
    put_raw(session, acholi, "FY2024/25", "ANC1", 50_000)
    put_raw(session, acholi, "FY2024/25", "IFA_30", 90_000)
    session.commit()
    csrf = login(client, "acholi.analyst")
    response = query_dashboard(client, auth_header(csrf), acholi.id)
    assert response.status_code == 201
    by_code = {row["indicator_code"]: row for row in response.json()["module_result"]["indicators"]}
    assert by_code["IFA_COVERAGE"]["raw_value"] > 100
    assert any(item["code"] == "over_100" for item in response.json()["insights"])

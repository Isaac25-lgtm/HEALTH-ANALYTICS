"""Authorised global search: geography and programme scope are enforced in the query."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select

from app.domain.enums import OrgUnitLevel
from app.models import OrgUnit, User, UserGeographyScope
from app.services.geography import create_org_unit
from app.services.search import scoped_search
from tests.conftest import auth_header, login
from tests.helpers import put_event


def _user(session, username):
    return session.scalar(select(User).where(User.username == username))


def _names(result):
    return [row["name"] for row in result["org_units"]]


def test_geography_scope_hides_siblings_and_ancestors(session):
    district = scoped_search(session, _user(session, "pader.focal"), "pader")
    assert set(_names(district)) == {"Pader", "Pader Town", "Pader HC III"}
    assert scoped_search(session, _user(session, "pader.focal"), "kitgum")["org_units"] == []
    assert scoped_search(session, _user(session, "pader.focal"), "acholi")["org_units"] == []
    assert scoped_search(session, _user(session, "pader.focal"), "ug")["org_units"] == []
    national = scoped_search(session, _user(session, "national.analyst"), "kitgum")
    assert _names(national) == ["Kitgum"]
    facility = scoped_search(session, _user(session, "paderhc3.user"), "pader")
    assert _names(facility) == ["Pader HC III"]


def test_geography_scope_path_wildcards_are_literal(session):
    uganda = session.scalar(select(OrgUnit).where(OrgUnit.code == "UG"))
    allowed_scope = create_org_unit(
        session,
        code="A_B",
        name="Allowed wildcard scope",
        level_type=OrgUnitLevel.DISTRICT,
        parent=uganda,
    )
    sibling_scope = create_org_unit(
        session,
        code="AXB",
        name="Sibling wildcard scope",
        level_type=OrgUnitLevel.DISTRICT,
        parent=uganda,
    )
    create_org_unit(
        session,
        code="ALLOWED_NEEDLE",
        name="Needle inside scope",
        level_type=OrgUnitLevel.FACILITY,
        parent=allowed_scope,
    )
    create_org_unit(
        session,
        code="FORBIDDEN_NEEDLE",
        name="Needle outside scope",
        level_type=OrgUnitLevel.FACILITY,
        parent=sibling_scope,
    )
    user = _user(session, "pader.focal")
    grant = session.scalar(select(UserGeographyScope).where(UserGeographyScope.user_id == user.id))
    grant.org_unit_id = allowed_scope.id
    session.flush()

    result = scoped_search(session, user, "needle")

    assert _names(result) == ["Needle inside scope"]


def test_programme_scope_limits_indicators(session):
    mnch_only = scoped_search(session, _user(session, "mnch.only"), "death")
    assert all(row["programme"] == "MNCH" for row in mnch_only["indicators"])
    full = scoped_search(session, _user(session, "national.analyst"), "death")
    assert any(row["programme"] == "MPDSR" for row in full["indicators"])
    mpdsr_only = scoped_search(session, _user(session, "mpdsr.analyst"), "anc1")
    assert mpdsr_only["indicators"] == []
    anc = scoped_search(session, _user(session, "national.analyst"), "anc1 coverage")
    assert anc["indicators"][0]["code"] == "ANC1_COVERAGE" and anc["indicators"][0]["module"] == "anc"


def test_wildcards_are_literal_and_short_queries_return_nothing(session):
    user = _user(session, "national.analyst")
    for query in ("%", "_", "%%", "a", " ", "\\"):
        result = scoped_search(session, user, query)
        assert result["org_units"] == [] and result["indicators"] == [], query


def test_search_never_returns_event_data(client, session):
    from app.models import OrgUnit

    pader = session.scalar(select(OrgUnit).where(OrgUnit.code == "PADER"))
    put_event(
        session,
        pader,
        event_uid="TEST_UID_SEARCH_EVENT",
        death_date=date(2024, 9, 1),
        data_values={"event_type": "maternal_death"},
    )
    session.commit()
    headers = auth_header(login(client, "admin.user"))
    for query in ("TEST_UID_SEARCH", "maternal_death", "pader"):
        response = client.get("/search", params={"q": query}, headers=headers)
        assert response.status_code == 200
        assert set(response.json()) == {"query", "org_units", "indicators"}
        assert "TEST_UID_SEARCH_EVENT" not in response.text
        assert "event_uid" not in response.text


def test_search_requires_authentication_and_bounds_input(client):
    assert client.get("/search", params={"q": "pader"}).status_code == 401


def test_search_through_http_uses_the_callers_scope(client, session):
    headers = auth_header(login(client, "pader.focal"))
    kitgum = client.get("/search", params={"q": "kitgum"}, headers=headers).json()
    assert kitgum["org_units"] == []
    assert client.get("/search", params={"q": "x" * 200}, headers=headers).status_code == 422
    assert client.get("/search", params={"q": "pa", "limit": 50}, headers=headers).status_code == 422

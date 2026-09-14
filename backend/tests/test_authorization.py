from sqlalchemy import select

from app.domain.enums import ActionPermission
from app.models import OrgUnit, User
from app.services.authorization import (
    AuthorizationError,
    can_access_programme,
    has_action,
    primary_landing_org_unit,
    require_org_unit_access,
)


def _user(session, username: str) -> User:
    return session.scalar(select(User).where(User.username == username))


def _unit(session, code: str) -> OrgUnit:
    return session.scalar(select(OrgUnit).where(OrgUnit.code == code))


def test_landing_national(session):
    user = _user(session, "national.analyst")
    landing = primary_landing_org_unit(session, user)
    assert landing.code == "UG"


def test_national_user_can_access_uganda_and_descendants(session):
    user = _user(session, "national.analyst")
    require_org_unit_access(session, user, _unit(session, "UG").id)
    require_org_unit_access(session, user, _unit(session, "TESO").id)
    require_org_unit_access(session, user, _unit(session, "PADER_HC_III").id)


def test_landing_regional(session):
    user = _user(session, "acholi.analyst")
    landing = primary_landing_org_unit(session, user)
    assert landing.code == "ACHOLI"


def test_landing_district(session):
    user = _user(session, "pader.focal")
    landing = primary_landing_org_unit(session, user)
    assert landing.code == "PADER"


def test_landing_facility(session):
    user = _user(session, "paderhc3.user")
    landing = primary_landing_org_unit(session, user)
    assert landing.code == "PADER_HC_III"


def test_regional_user_cannot_access_sibling_region(session):
    user = _user(session, "acholi.analyst")
    teso = _unit(session, "TESO")
    try:
        require_org_unit_access(session, user, teso.id)
        raise AssertionError("sibling region must be denied")
    except AuthorizationError as error:
        assert error.code == "forbidden_geography"


def test_regional_user_cannot_access_national(session):
    user = _user(session, "acholi.analyst")
    uganda = _unit(session, "UG")
    try:
        require_org_unit_access(session, user, uganda.id)
        raise AssertionError("national scope must be denied")
    except AuthorizationError as error:
        assert error.code == "forbidden_geography"


def test_district_user_can_access_descendants_only(session):
    user = _user(session, "pader.focal")
    require_org_unit_access(session, user, _unit(session, "PADER_HC_III").id)
    try:
        require_org_unit_access(session, user, _unit(session, "KITGUM").id)
        raise AssertionError("sibling district must be denied")
    except AuthorizationError as error:
        assert error.code == "forbidden_geography"


def test_mnch_only_cannot_access_epi(session):
    user = _user(session, "mnch.only")
    assert can_access_programme(session, user, "MNCH")
    assert not can_access_programme(session, user, "EPI")
    assert not can_access_programme(session, user, "MPDSR")


def test_view_only_cannot_export(session):
    user = _user(session, "view.only")
    assert has_action(session, user, ActionPermission.VIEW)
    assert not has_action(session, user, ActionPermission.EXPORT)


def test_mpdsr_event_permission_is_separate(session):
    national = _user(session, "national.analyst")
    mpdsr = _user(session, "mpdsr.analyst")
    assert not has_action(session, national, ActionPermission.VIEW_MPDSR_EVENTS)
    assert has_action(session, mpdsr, ActionPermission.VIEW_MPDSR_EVENTS)
    assert not has_action(session, mpdsr, ActionPermission.EXPORT_MPDSR_LINELIST)

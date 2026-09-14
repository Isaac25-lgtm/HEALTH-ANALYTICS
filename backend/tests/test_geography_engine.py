from sqlalchemy import select

from app.models import OrgUnit
from app.services.geography import (
    GeographyError,
    ancestors,
    assign_parent,
    descendants,
    unmapped_dhis2_org_units,
    validate_bulk_rows,
    would_create_cycle,
)
from tests.helpers import map_ou


def test_ancestors_and_descendants(session):
    uganda = session.scalar(select(OrgUnit).where(OrgUnit.code == "UG"))
    hc3 = session.scalar(select(OrgUnit).where(OrgUnit.code == "PADER_HC_III"))
    chain = [unit.code for unit in ancestors(session, hc3)]
    assert "PADER" in chain
    assert "UG" in chain
    kids = {unit.code for unit in descendants(session, uganda)}
    assert "PADER_HC_III" in kids
    assert "TESO" in kids


def test_cycle_prevention(session):
    uganda = session.scalar(select(OrgUnit).where(OrgUnit.code == "UG"))
    pader = session.scalar(select(OrgUnit).where(OrgUnit.code == "PADER"))
    assert would_create_cycle(session, uganda, pader)
    try:
        assign_parent(session, uganda, pader)
        raise AssertionError("cycle must be rejected")
    except GeographyError as error:
        assert error.code == "cycle_detected"


def test_bulk_validation_and_unmapped(session):
    uganda = session.scalar(select(OrgUnit).where(OrgUnit.code == "UG"))
    errors = validate_bulk_rows(
        session,
        [
            {"code": "X", "parent_code": "MISSING", "level_type": "district"},
            {"code": "X", "parent_code": "UG", "level_type": "nope"},
        ],
    )
    assert errors
    map_ou(session, uganda, "TEST_UID_UG")
    missing = unmapped_dhis2_org_units(session, ["TEST_UID_UG", "TEST_UID_UNKNOWN"])
    assert missing == ["TEST_UID_UNKNOWN"]

from sqlalchemy import select

from app.domain.enums import OrgUnitLevel
from app.models import OrgUnit
from app.services.authorization import child_org_units, is_descendant_or_self


def test_hierarchy_paths(session):
    uganda = session.scalar(select(OrgUnit).where(OrgUnit.code == "UG"))
    acholi = session.scalar(select(OrgUnit).where(OrgUnit.code == "ACHOLI"))
    pader = session.scalar(select(OrgUnit).where(OrgUnit.code == "PADER"))
    teso = session.scalar(select(OrgUnit).where(OrgUnit.code == "TESO"))
    hc3 = session.scalar(select(OrgUnit).where(OrgUnit.code == "PADER_HC_III"))
    assert uganda.level_type == OrgUnitLevel.COUNTRY.value
    assert acholi.path.startswith(uganda.path)
    assert pader.path.startswith(acholi.path)
    assert is_descendant_or_self(hc3, uganda)
    assert is_descendant_or_self(pader, acholi)
    assert not is_descendant_or_self(pader, teso)


def test_children_of_acholi(session):
    acholi = session.scalar(select(OrgUnit).where(OrgUnit.code == "ACHOLI"))
    children = {unit.code for unit in child_org_units(session, acholi)}
    assert children == {"PADER", "KITGUM"}

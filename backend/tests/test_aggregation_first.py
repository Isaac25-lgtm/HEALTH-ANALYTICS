from sqlalchemy import select

from app.models import OrgUnit
from app.services.calculation import evaluate_formula
from tests.helpers import put_raw


def test_parent_equals_sum_not_mean_of_percentages(session):
    pader = session.scalar(select(OrgUnit).where(OrgUnit.code == "PADER"))
    kitgum = session.scalar(select(OrgUnit).where(OrgUnit.code == "KITGUM"))
    acholi = session.scalar(select(OrgUnit).where(OrgUnit.code == "ACHOLI"))
    put_raw(session, pader, "FY2024/25", "ANC1_FT", 80)
    put_raw(session, pader, "FY2024/25", "ANC1", 100)  # 80%
    put_raw(session, kitgum, "FY2024/25", "ANC1_FT", 10)
    put_raw(session, kitgum, "FY2024/25", "ANC1", 400)  # 2.5%
    from app.models import Indicator, IndicatorVersion

    indicator = session.scalar(select(Indicator).where(Indicator.code == "ANC1_FIRST_TRIMESTER"))
    version = session.scalar(
        select(IndicatorVersion).where(IndicatorVersion.indicator_id == indicator.id)
    )
    parent = evaluate_formula(
        session, org_unit=acholi, period="FY2024/25", version=version, programme_id=indicator.programme_id
    )
    assert parent.numerator == 90
    assert parent.denominator == 500
    assert parent.raw_value == 18
    mean_of_children = (80 + 2.5) / 2
    assert parent.raw_value != mean_of_children

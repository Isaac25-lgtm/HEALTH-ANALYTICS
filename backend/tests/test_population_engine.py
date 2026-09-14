from sqlalchemy import select

from app.models import OrgUnit
from app.services.population import period_fraction, period_target, resolve_population, resolve_population_year
from tests.helpers import put_population


def _unit(session, code: str) -> OrgUnit:
    return session.scalar(select(OrgUnit).where(OrgUnit.code == code))


def test_fy_2024_25_resolves_to_2024(session):
    assert resolve_population_year(session, "FY2024/25") == 2024


def test_fy_2025_26_resolves_to_2025(session):
    assert resolve_population_year(session, "FY2025/26") == 2025


def test_period_fractions():
    assert period_fraction("FY2024/25") == 1
    assert period_fraction("2024Q1") == 0.25
    assert period_fraction("202407") == 1 / 12
    assert period_fraction("2024H1") == 0.5


def test_period_target_applies_fraction_once():
    assert period_target(10000, 0.05, "2024Q1") == 10000 * 0.05 * 0.25


def test_missing_population_is_unavailable_not_zero(session):
    uganda = _unit(session, "UG")
    result = resolve_population(session, uganda, period_key="FY2024/25")
    assert result.status == "unavailable"
    assert result.population is None


def test_direct_population_used(session):
    uganda = _unit(session, "UG")
    put_population(session, uganda, 2024, 100000)
    result = resolve_population(session, uganda, period_key="FY2024/25")
    assert result.status == "ok"
    assert result.population == 100000
    assert result.year == 2024


def test_parent_does_not_double_count_children(session):
    uganda = _unit(session, "UG")
    acholi = _unit(session, "ACHOLI")
    teso = _unit(session, "TESO")
    put_population(session, uganda, 2024, 90000)
    put_population(session, acholi, 2024, 40000)
    put_population(session, teso, 2024, 50000)
    result = resolve_population(session, uganda, period_key="FY2024/25")
    assert result.population == 90000


def test_complete_children_sum_when_parent_missing(session):
    uganda = _unit(session, "UG")
    acholi = _unit(session, "ACHOLI")
    teso = _unit(session, "TESO")
    put_population(session, acholi, 2024, 40000)
    put_population(session, teso, 2024, 50000)
    result = resolve_population(session, uganda, period_key="FY2024/25")
    assert result.population == 90000


def test_service_derived_works_without_facility_population(session):
    hc3 = _unit(session, "PADER_HC_III")
    from app.models import Indicator, IndicatorVersion
    from app.services.calculation import evaluate_formula
    from tests.helpers import put_raw

    put_raw(session, hc3, "FY2024/25", "CS", 8)
    put_raw(session, hc3, "FY2024/25", "DELIVERIES", 80)
    indicator = session.scalar(select(Indicator).where(Indicator.code == "CAESAREAN_SECTION"))
    version = session.scalar(select(IndicatorVersion).where(IndicatorVersion.indicator_id == indicator.id))
    measure = evaluate_formula(
        session, org_unit=hc3, period="FY2024/25", version=version, programme_id=indicator.programme_id
    )
    assert measure.raw_value == 10
    pop = resolve_population(session, hc3, period_key="FY2024/25")
    assert pop.status == "unavailable"


def test_incomplete_children_do_not_become_zero(session):
    uganda = _unit(session, "UG")
    acholi = _unit(session, "ACHOLI")
    put_population(session, acholi, 2024, 40000)
    result = resolve_population(session, uganda, period_key="FY2024/25")
    assert result.status == "unavailable"
    assert result.population is None

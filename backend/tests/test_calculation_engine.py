
from sqlalchemy import select

from app.models import Indicator, IndicatorVersion, OrgUnit
from app.services.calculation import evaluate_formula
from tests.helpers import put_period_rule, put_population, put_raw


def _unit(session, code):
    return session.scalar(select(OrgUnit).where(OrgUnit.code == code))


def _version(session, code):
    indicator = session.scalar(select(Indicator).where(Indicator.code == code))
    return session.scalar(
        select(IndicatorVersion).where(
            IndicatorVersion.indicator_id == indicator.id,
            IndicatorVersion.is_current.is_(True),
        )
    )


def _eval(session, code, org="UG", period="FY2024/25"):
    indicator = session.scalar(select(Indicator).where(Indicator.code == code))
    return evaluate_formula(
        session,
        org_unit=_unit(session, org),
        period=period,
        version=_version(session, code),
        programme_id=indicator.programme_id,
    )


def test_anc1_boundaries(session):
    uganda = _unit(session, "UG")
    put_population(session, uganda, 2024, 10000)
    put_raw(session, uganda, "FY2024/25", "ANC1", 475)  # 475/500 = 95%
    measure = _eval(session, "ANC1_COVERAGE")
    assert round(measure.raw_value, 1) == 95.0
    assert measure.status == "green"
    put_raw(session, uganda, "FY2024/25", "ANC1", 474.5)  # 94.9%
    measure = _eval(session, "ANC1_COVERAGE")
    assert round(measure.raw_value, 1) == 94.9
    assert measure.status == "yellow"


def test_anc1_green_yellow_red(session):
    uganda = _unit(session, "UG")
    put_population(session, uganda, 2024, 20000)
    # denom = 20000 * 0.05 = 1000
    put_raw(session, uganda, "FY2024/25", "ANC1", 950)
    assert _eval(session, "ANC1_COVERAGE").status == "green"
    from sqlalchemy import update

    from app.models import RawAggregateValue

    session.execute(update(RawAggregateValue).values(is_current=False))
    put_raw(session, uganda, "FY2024/25", "ANC1", 750)
    assert _eval(session, "ANC1_COVERAGE").status == "yellow"
    session.execute(update(RawAggregateValue).values(is_current=False))
    put_raw(session, uganda, "FY2024/25", "ANC1", 749)
    assert _eval(session, "ANC1_COVERAGE").status == "red"


def test_first_trimester_and_service_not_period_adjusted(session):
    uganda = _unit(session, "UG")
    put_raw(session, uganda, "2024Q1", "ANC1_FT", 40)
    put_raw(session, uganda, "2024Q1", "ANC1", 100)
    measure = _eval(session, "ANC1_FIRST_TRIMESTER", period="2024Q1")
    assert measure.raw_value == 40
    assert measure.denominator == 100


def test_teenage_inverse_boundaries(session):
    uganda = _unit(session, "UG")
    put_raw(session, uganda, "FY2024/25", "ANC1_AGE_LT15", 2)
    put_raw(session, uganda, "FY2024/25", "ANC1_AGE_15_19", 2)
    put_raw(session, uganda, "FY2024/25", "ANC1", 100)
    assert _eval(session, "TEENAGE_PREGNANCY").status == "green"
    from sqlalchemy import update

    from app.models import RawAggregateValue

    session.execute(update(RawAggregateValue).values(is_current=False))
    put_raw(session, uganda, "FY2024/25", "ANC1_AGE_LT15", 5)
    put_raw(session, uganda, "FY2024/25", "ANC1_AGE_15_19", 0)
    put_raw(session, uganda, "FY2024/25", "ANC1", 100)
    assert _eval(session, "TEENAGE_PREGNANCY").status == "yellow"
    session.execute(update(RawAggregateValue).values(is_current=False))
    put_raw(session, uganda, "FY2024/25", "ANC1_AGE_LT15", 13)
    put_raw(session, uganda, "FY2024/25", "ANC1_AGE_15_19", 0)
    put_raw(session, uganda, "FY2024/25", "ANC1", 100)
    assert _eval(session, "TEENAGE_PREGNANCY").status == "red"


def test_caesarean_desired_range(session):
    uganda = _unit(session, "UG")
    put_raw(session, uganda, "FY2024/25", "CS", 10)
    put_raw(session, uganda, "FY2024/25", "DELIVERIES", 100)
    assert _eval(session, "CAESAREAN_SECTION").status == "green"
    from sqlalchemy import update

    from app.models import RawAggregateValue

    session.execute(update(RawAggregateValue).values(is_current=False))
    put_raw(session, uganda, "FY2024/25", "CS", 4)
    put_raw(session, uganda, "FY2024/25", "DELIVERIES", 100)
    assert _eval(session, "CAESAREAN_SECTION").status == "yellow"
    session.execute(update(RawAggregateValue).values(is_current=False))
    put_raw(session, uganda, "FY2024/25", "CS", 2)
    put_raw(session, uganda, "FY2024/25", "DELIVERIES", 100)
    assert _eval(session, "CAESAREAN_SECTION").status == "red"


def test_institutional_delivery_over_100_not_blue(session):
    uganda = _unit(session, "UG")
    put_population(session, uganda, 2024, 10000)
    put_raw(session, uganda, "FY2024/25", "DELIVERIES", 600)  # denom 485, >100%
    measure = _eval(session, "INSTITUTIONAL_DELIVERY")
    assert measure.raw_value > 100
    assert measure.status == "green"


def test_kmc_over_100_is_blue(session):
    uganda = _unit(session, "UG")
    put_raw(session, uganda, "FY2024/25", "KMC_PERCENT", 110)
    assert _eval(session, "KMC").status == "blue"


def test_resuscitation_zero_denominator_na(session):
    uganda = _unit(session, "UG")
    put_raw(session, uganda, "FY2024/25", "RESUSCITATED", 0)
    put_raw(session, uganda, "FY2024/25", "BIRTH_ASPHYXIA", 0)
    measure = _eval(session, "SUCCESSFUL_RESUSCITATION")
    assert measure.raw_value is None
    assert measure.status == "n_a"


def test_resuscitation_over_100_blue(session):
    uganda = _unit(session, "UG")
    put_raw(session, uganda, "FY2024/25", "RESUSCITATED", 12)
    put_raw(session, uganda, "FY2024/25", "BIRTH_ASPHYXIA", 10)
    assert _eval(session, "SUCCESSFUL_RESUSCITATION").status == "blue"


def test_pmr_uses_1000_not_percent(session):
    uganda = _unit(session, "UG")
    put_raw(session, uganda, "FY2024/25", "FRESH_SB", 5)
    put_raw(session, uganda, "FY2024/25", "MACERATED_SB", 3)
    put_raw(session, uganda, "FY2024/25", "NEWBORN_DEATHS", 4)
    put_raw(session, uganda, "FY2024/25", "DELIVERIES", 1000)
    measure = _eval(session, "PMR")
    assert measure.raw_value == 12
    assert measure.status == "green"
    version = _version(session, "PMR")
    assert version.unit != "%"
    assert "%" not in version.unit


def test_fresh_stillbirth_and_mmr_units(session):
    uganda = _unit(session, "UG")
    put_raw(session, uganda, "FY2024/25", "FRESH_SB", 5)
    put_raw(session, uganda, "FY2024/25", "DELIVERIES", 1000)
    p = _eval(session, "FRESH_STILLBIRTH_RATE")
    assert p.raw_value == 5
    assert p.status == "green"
    put_raw(session, uganda, "FY2024/25", "MATERNAL_DEATHS", 183)
    put_raw(session, uganda, "FY2024/25", "LIVE_BIRTHS", 100000)
    m = _eval(session, "MMR")
    assert m.raw_value == 183
    assert m.status == "green"
    assert "percent" not in _version(session, "MMR").unit.lower()


def test_mv4_coefficient_4_3(session):
    uganda = _unit(session, "UG")
    put_population(session, uganda, 2024, 10000)
    put_raw(session, uganda, "FY2024/25", "MV4", 43)
    measure = _eval(session, "MV4_COVERAGE")
    assert measure.denominator == 10000 * 0.043
    assert round(measure.raw_value, 1) == 10.0
    # Owner-approved EPI bands (v2-epi-bands, 2026-09-24): coverage below 80% is red.
    assert measure.status == "red"


def test_missing_source_is_not_zero(session):
    uganda = _unit(session, "UG")
    put_population(session, uganda, 2024, 10000)
    measure = _eval(session, "ANC1_COVERAGE")
    assert measure.numerator is None
    assert measure.raw_value is None


def test_ifa_over_100_retained(session):
    uganda = _unit(session, "UG")
    put_raw(session, uganda, "FY2024/25", "IFA_30", 120)
    put_raw(session, uganda, "FY2024/25", "ANC1", 100)
    measure = _eval(session, "IFA_COVERAGE")
    assert measure.raw_value == 120
    assert measure.status == "green"


def test_period_adjustment_once_for_quarter(session):
    uganda = _unit(session, "UG")
    put_population(session, uganda, 2024, 12000)
    put_raw(session, uganda, "2024Q1", "ANC1", 15)
    # Quarterly population selection is not an approved rule by default (OPEN_ITEMS).
    unresolved = _eval(session, "ANC1_COVERAGE", period="2024Q1")
    assert unresolved.denominator is None
    assert unresolved.reason_code == "population_rule_missing"
    # With an explicit approved calendar-year rule covering quarters, the fraction applies once.
    put_period_rule(session, "2024", 2024, kinds=["quarter"], scope="calendar_year")
    measure = _eval(session, "ANC1_COVERAGE", period="2024Q1")
    assert measure.denominator == 12000 * 0.05 * 0.25


def test_remaining_coverage_indicators_execute(session):
    uganda = _unit(session, "UG")
    put_population(session, uganda, 2024, 10000)
    put_raw(session, uganda, "FY2024/25", "ANC1", 100)
    put_raw(session, uganda, "FY2024/25", "ANC4", 250)
    put_raw(session, uganda, "FY2024/25", "ANC8", 40)
    put_raw(session, uganda, "FY2024/25", "IPT3", 250)
    put_raw(session, uganda, "FY2024/25", "HB_TESTED", 50)
    put_raw(session, uganda, "FY2024/25", "ULTRASOUND", 50)
    put_raw(session, uganda, "FY2024/25", "BCG", 48.5)
    assert _eval(session, "ANC4_COVERAGE").status == "yellow"
    assert _eval(session, "ANC8_COVERAGE").status == "yellow"
    assert _eval(session, "IPT3_COVERAGE").status == "yellow"
    assert _eval(session, "HB_TESTING").raw_value == 50
    assert _eval(session, "OBSTETRIC_ULTRASOUND").raw_value == 50
    assert round(_eval(session, "BCG_COVERAGE").raw_value, 1) == 10.0
    put_raw(session, uganda, "FY2024/25", "OPV2", 43)
    put_raw(session, uganda, "FY2024/25", "PENTA2", 43)
    put_raw(session, uganda, "FY2024/25", "ROTAV2", 43)
    put_raw(session, uganda, "FY2024/25", "PCV2", 43)
    put_raw(session, uganda, "FY2024/25", "PCV3", 43)
    put_raw(session, uganda, "FY2024/25", "IPV2", 43)
    for code in (
        "OPV2_COVERAGE",
        "PENTA2_COVERAGE",
        "ROTAV2_COVERAGE",
        "PCV2_COVERAGE",
        "PCV3_COVERAGE",
        "IPV2_COVERAGE",
    ):
        measure = _eval(session, code)
        assert measure.denominator == 10000 * 0.043
        assert measure.status == "red"


def test_first_trimester_and_ifa_band_edges(session):
    uganda = _unit(session, "UG")
    put_raw(session, uganda, "FY2024/25", "ANC1_FT", 45)
    put_raw(session, uganda, "FY2024/25", "ANC1", 100)
    assert _eval(session, "ANC1_FIRST_TRIMESTER").status == "green"
    put_raw(session, uganda, "FY2024/25", "ANC1_FT", 29.9)
    assert _eval(session, "ANC1_FIRST_TRIMESTER").status == "red"
    put_raw(session, uganda, "FY2024/25", "IFA_30", 95)
    assert _eval(session, "IFA_COVERAGE").status == "green"
    put_raw(session, uganda, "FY2024/25", "IFA_30", 74.9)
    assert _eval(session, "IFA_COVERAGE").status == "red"

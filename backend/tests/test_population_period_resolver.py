"""Central population/period resolution and calculation verification (work packages I, J, K).

Population years, period fractions and target denominators are resolved in exactly one place.
Values come from a fixture derived from the owner-approved workbook, never retyped by hand.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app.domain.periods import parse_period
from app.models import Indicator, IndicatorVersion, OrgUnit
from app.services.calculation import evaluate_formula, run_calculation
from app.services.population import (
    TargetDenominator,
    period_fraction,
    resolve_population_year,
    resolve_target_denominator,
)
from app.services.population_workbook import VERIFIED_SHA256
from tests.helpers import put_population, put_raw

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "workbook_population_reference.json").read_text(encoding="utf-8")
)

# Approved coefficients from the indicator catalogue.
PREGNANCY_COEFFICIENT = 0.05
DELIVERY_COEFFICIENT = 0.0485
INFANT_COEFFICIENT = 0.043


def _unit(session, code="PADER"):
    return session.scalar(select(OrgUnit).where(OrgUnit.code == code))


def _version(session, code: str) -> IndicatorVersion:
    indicator = session.scalar(select(Indicator).where(Indicator.code == code))
    return session.scalar(
        select(IndicatorVersion).where(
            IndicatorVersion.indicator_id == indicator.id, IndicatorVersion.is_current.is_(True)
        )
    )


def _programme_id(session, code: str):
    indicator = session.scalar(select(Indicator).where(Indicator.code == code))
    return indicator.programme_id


def _measure(session, org, period: str, code: str):
    return evaluate_formula(
        session,
        org_unit=org,
        period=period,
        version=_version(session, code),
        programme_id=_programme_id(session, code),
    )


def pader_population(year: int) -> int:
    return FIXTURE["units"]["Pader"]["values"][str(year)]


@pytest.fixture()
def pader_with_workbook_population(session):
    """Pader loaded with its real workbook populations for 2024-2030."""
    org = _unit(session)
    for year in FIXTURE["years"]:
        put_population(session, org, year, pader_population(year), code=f"WORKBOOK_{year}")
    session.commit()
    return org


# ---------------------------------------------------------------------------
# Fixture integrity
# ---------------------------------------------------------------------------


def test_fixture_is_derived_from_the_approved_workbook():
    assert FIXTURE["source_sha256"].upper() == VERIFIED_SHA256
    assert FIXTURE["source_display_name"] == "Uganda_District_City_Populations_2024_2030 (1).xlsx"
    assert FIXTURE["years"] == list(range(2024, 2031))
    assert pader_population(2025) == 248_910
    assert "VERIFIED FIXTURE" in FIXTURE["label"]


# ---------------------------------------------------------------------------
# Approved year rules
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("period", "expected_year"),
    [
        ("2024", 2024),
        ("2025", 2025),
        ("2026", 2026),
        ("FY2024/25", 2024),
        ("FY2025/26", 2025),
        ("FY2026/27", 2026),
        ("FY2027/28", 2027),
        ("FY2028/29", 2028),
        ("FY2029/30", 2029),
        # Child periods of a financial year use that financial year's base year.
        ("FY2025/26Q1", 2025),
        ("FY2025/26Q4", 2025),
        ("202508", 2025),
        ("202602", 2025),
        ("2026Q1", 2025),
        ("2025H2", 2025),
        ("2026H1", 2025),
    ],
)
def test_population_year_follows_the_approved_rules(session, period, expected_year):
    assert resolve_population_year(session, period) == expected_year


def test_period_fractions_match_the_approved_values():
    assert period_fraction("FY2025/26") == 1.0
    assert period_fraction("2025") == 1.0
    assert period_fraction("2025H2") == pytest.approx(6 / 12)
    assert period_fraction("FY2025/26Q1") == pytest.approx(3 / 12)
    assert period_fraction("2025Q4") == pytest.approx(3 / 12)
    assert period_fraction("202508") == pytest.approx(1 / 12)


# ---------------------------------------------------------------------------
# Work package K: real population regression
# ---------------------------------------------------------------------------


def _target(session, org, period, coefficient) -> TargetDenominator:
    return resolve_target_denominator(session, org, period_key=period, coefficient=coefficient)


def test_pader_fy2025_26_targets_use_the_real_workbook_population(session, pader_with_workbook_population):
    org = pader_with_workbook_population
    population = pader_population(2025)
    pregnancies = _target(session, org, "FY2025/26", PREGNANCY_COEFFICIENT)
    deliveries = _target(session, org, "FY2025/26", DELIVERY_COEFFICIENT)
    infants = _target(session, org, "FY2025/26", INFANT_COEFFICIENT)
    assert pregnancies.population_year == 2025
    assert pregnancies.population == population
    assert pregnancies.value == pytest.approx(population * 0.05)
    assert deliveries.value == pytest.approx(population * 0.0485)
    assert infants.value == pytest.approx(population * 0.043)
    # MV1-MV4 share the infant target.
    for _antigen in ("MV1", "MV2", "MV3", "MV4"):
        assert _target(session, org, "FY2025/26", INFANT_COEFFICIENT).value == pytest.approx(population * 0.043)
    assert pregnancies.fraction == 1.0
    assert pregnancies.annual_target == pytest.approx(population * 0.05)
    assert pregnancies.adjusted_target == pregnancies.annual_target


@pytest.mark.parametrize(
    ("period", "fraction"),
    [("FY2025/26", 1.0), ("2025", 1.0), ("2025H2", 6 / 12), ("FY2025/26Q2", 3 / 12), ("202510", 1 / 12)],
)
def test_period_fraction_scales_only_the_annual_target(session, pader_with_workbook_population, period, fraction):
    org = pader_with_workbook_population
    year = resolve_population_year(session, period)
    population = pader_population(year)
    target = _target(session, org, period, PREGNANCY_COEFFICIENT)
    assert target.ok
    assert target.population == population
    assert target.annual_target == pytest.approx(population * 0.05)
    assert target.adjusted_target == pytest.approx(population * 0.05 * fraction)
    assert target.value == target.adjusted_target
    assert target.period_kind == parse_period(period).kind
    assert target.parent_fy == parse_period(period).parent_fy


def test_provenance_records_every_step_of_the_resolution(session, pader_with_workbook_population):
    target = _target(session, pader_with_workbook_population, "FY2025/26Q1", INFANT_COEFFICIENT)
    provenance = target.provenance()
    assert provenance["period_kind"] == "fy_quarter"
    assert provenance["parent_fy"] == "FY2025/26"
    assert provenance["population_year"] == 2025
    assert provenance["period_fraction"] == pytest.approx(0.25)
    assert provenance["coefficient"] == INFANT_COEFFICIENT
    assert provenance["annual_target"] == pytest.approx(pader_population(2025) * 0.043)
    assert provenance["adjusted_target"] == pytest.approx(pader_population(2025) * 0.043 * 0.25)
    assert provenance["population"] == pader_population(2025)
    assert provenance["population_version_id"]


def test_calculated_values_carry_the_denominator_provenance(session, pader_with_workbook_population):
    org = pader_with_workbook_population
    put_raw(session, org, "FY2025/26", "ANC1", 10_000)
    run = run_calculation(
        session, org_unit=org, period="FY2025/26", user=None, indicator_codes=["ANC1_COVERAGE"]
    )
    from app.models import CalculatedValue

    value = session.scalar(select(CalculatedValue).where(CalculatedValue.calculation_run_id == run.id))
    provenance = value.denominator_provenance
    assert provenance["population_year"] == 2025
    assert provenance["period_fraction"] == 1.0
    assert provenance["coefficient"] == PREGNANCY_COEFFICIENT
    assert float(value.denominator) == pytest.approx(pader_population(2025) * 0.05)
    assert float(value.raw_value) == pytest.approx(10_000 / (pader_population(2025) * 0.05) * 100)


def test_service_derived_denominators_are_never_period_adjusted(session, pader_with_workbook_population):
    org = pader_with_workbook_population
    for period in ("FY2025/26", "FY2025/26Q1", "202510"):
        put_raw(session, org, period, "ANC1", 800)
        put_raw(session, org, period, "ANC1_FT", 200)
    session.flush()
    results = {
        period: _measure(session, org, period, "ANC1_FIRST_TRIMESTER")
        for period in ("FY2025/26", "FY2025/26Q1", "202510")
    }
    for period, measure in results.items():
        assert measure.denominator == 800, period  # the reported ANC1 count, never scaled
        assert measure.raw_value == pytest.approx(25.0), period
        assert measure.denominator_provenance is None


def test_population_derived_indicator_scales_with_the_period(session, pader_with_workbook_population):
    org = pader_with_workbook_population
    put_raw(session, org, "FY2025/26", "ANC1", 12_000)
    put_raw(session, org, "FY2025/26Q1", "ANC1", 3_000)
    session.flush()
    annual = _measure(session, org, "FY2025/26", "ANC1_COVERAGE")
    quarter = _measure(session, org, "FY2025/26Q1", "ANC1_COVERAGE")
    population = pader_population(2025)
    assert annual.denominator == pytest.approx(population * 0.05)
    assert quarter.denominator == pytest.approx(population * 0.05 * 0.25)
    assert quarter.denominator_provenance["period_fraction"] == pytest.approx(0.25)


# ---------------------------------------------------------------------------
# Work package J: lower levels
# ---------------------------------------------------------------------------


def test_sub_county_without_an_approved_population_is_unavailable_not_zero(session, pader_with_workbook_population):
    sub_county = session.scalar(select(OrgUnit).where(OrgUnit.level_type == "sub_county"))
    assert sub_county is not None
    put_raw(session, sub_county, "FY2025/26", "ANC1", 120)
    session.flush()
    measure = _measure(session, sub_county, "FY2025/26", "ANC1_COVERAGE")
    assert measure.raw_value is None
    assert measure.denominator is None
    assert measure.numerator != 0  # the numerator is real; only the denominator is missing
    assert measure.reason_code in {"population_unavailable", "population_denominator_unavailable"}
    assert measure.quality_status == "blue"
    # District population is never divided down to the sub-county.
    target = _target(session, sub_county, "FY2025/26", PREGNANCY_COEFFICIENT)
    assert not target.ok and target.value is None


def test_service_derived_indicators_still_calculate_at_sub_county(session):
    sub_county = session.scalar(select(OrgUnit).where(OrgUnit.level_type == "sub_county"))
    put_raw(session, sub_county, "FY2025/26", "ANC1", 400)
    put_raw(session, sub_county, "FY2025/26", "ANC1_FT", 100)
    session.flush()
    measure = _measure(session, sub_county, "FY2025/26", "ANC1_FIRST_TRIMESTER")
    assert measure.raw_value == pytest.approx(25.0)


def test_periods_beyond_the_approved_source_years_fail_closed(session, pader_with_workbook_population):
    target = _target(session, pader_with_workbook_population, "FY2032/33", PREGNANCY_COEFFICIENT)
    assert not target.ok
    assert target.reason_code == "population_rule_missing"
    assert target.value is None and target.adjusted_target is None

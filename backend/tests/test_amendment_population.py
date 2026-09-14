"""Amendment §4 (explicit period-population rules) and §5 (facility-only catchment)."""

from sqlalchemy import select

from app.domain.enums import ApprovalStatus, OrgUnitLevel, PopulationType
from app.models import (
    FacilityPopulationEntry,
    Indicator,
    IndicatorVersion,
    OrgUnit,
    Programme,
    User,
)
from app.services.calculation import evaluate_formula
from app.services.geography import create_org_unit
from app.services.population import (
    approve_facility_population,
    enter_facility_population,
    resolve_population,
    resolve_population_year,
    resolve_population_year_rule,
)
from tests.helpers import put_period_rule, put_population, put_raw


def _unit(session, code):
    return session.scalar(select(OrgUnit).where(OrgUnit.code == code))


def _programme(session, code):
    return session.scalar(select(Programme).where(Programme.code == code))


def _eval(session, code, org, period):
    indicator = session.scalar(select(Indicator).where(Indicator.code == code))
    version = session.scalar(
        select(IndicatorVersion).where(
            IndicatorVersion.indicator_id == indicator.id,
            IndicatorVersion.is_current.is_(True),
        )
    )
    return evaluate_formula(session, org_unit=org, period=period, version=version, programme_id=indicator.programme_id)


def test_fy_rule_covers_its_child_periods_but_not_unapproved_years(session):
    """Owner decision D-041 (2026-09-14) extended the FY rule to its child periods.

    Periods outside the approved population source years still fail closed.
    """
    assert resolve_population_year(session, "FY2024/25") == 2024
    assert resolve_population_year(session, "FY2024/25Q1") == 2024
    assert resolve_population_year(session, "202407") == 2024
    assert resolve_population_year(session, "2024Q3") == 2024
    missing = resolve_population_year_rule(session, "203207")
    assert missing.year is None
    assert missing.reason_code == "population_rule_missing"
    assert "month" in (missing.reason or "")


def test_calendar_year_rule_applies_only_to_listed_kinds(session):
    # 2032 is outside the approved source years, so nothing is seeded for it.
    assert resolve_population_year(session, "2032") is None
    put_period_rule(session, "2032", 2032, kinds=["year"], scope="calendar_year")
    assert resolve_population_year(session, "2032") == 2032
    assert resolve_population_year(session, "2032Q1") is None
    put_period_rule(session, "2032", 2032, kinds=["year", "quarter"], scope="calendar_year")
    assert resolve_population_year(session, "2032Q1") == 2032


def test_conflicting_rules_leave_period_unresolved(session):
    put_period_rule(session, "FY2025/26", 2025, kinds=["fy", "month"])
    assert resolve_population_year(session, "202507") == 2025
    put_period_rule(session, "2025", 2026, kinds=["month"], scope="calendar_year")
    assert resolve_population_year(session, "202507") is None
    assert "conflict" in (resolve_population_year_rule(session, "202507").reason or "")


def test_unapproved_rule_is_ignored(session):
    put_period_rule(session, "FY2032/33", 2032, kinds=["fy"], approval_status=ApprovalStatus.DRAFT.value)
    assert resolve_population_year(session, "FY2032/33") is None


def test_other_programme_rule_is_never_used(session):
    epi = _programme(session, "EPI")
    mnch = _programme(session, "MNCH")
    put_period_rule(session, "FY2032/33", 2032, kinds=["fy"], programme_id=epi.id)
    assert resolve_population_year(session, "FY2032/33", epi.id) == 2032
    assert resolve_population_year(session, "FY2032/33", mnch.id) is None
    assert resolve_population_year(session, "FY2032/33") is None


def test_missing_monthly_rule_blocks_only_population_derived_values(session):
    """A period with no approved rule (here, beyond the approved source years) fails closed for
    population-derived indicators while service-derived ones still calculate."""
    uganda = _unit(session, "UG")
    put_population(session, uganda, 2024, 120_000)
    put_raw(session, uganda, "203207", "ANC1", 400)
    put_raw(session, uganda, "203207", "ANC1_FT", 100)
    coverage = _eval(session, "ANC1_COVERAGE", uganda, "203207")
    assert coverage.raw_value is None
    assert coverage.reason_code == "population_rule_missing"
    service = _eval(session, "ANC1_FIRST_TRIMESTER", uganda, "203207")
    assert service.raw_value == 25


def _approved_facility_entry(session, facility, population=1500):
    editor = session.scalar(select(User).where(User.username == "pader.focal"))
    admin = session.scalar(select(User).where(User.username == "admin.user"))
    entry = enter_facility_population(
        session,
        editor,
        org_unit_id=facility.id,
        year=2024,
        population=population,
        source_name="Synthetic catchment test",
        population_type=PopulationType.FACILITY_CATCHMENT_ESTIMATE.value,
        reason="facility-only test",
    )
    return approve_facility_population(session, admin, entry.id, reason="ok")


def test_facility_entries_do_not_manufacture_parent_population(session):
    uganda = _unit(session, "UG")
    facility = _unit(session, "PADER_HC_III")
    put_population(session, uganda, 2024, 1_000_000, code="NATIONAL_TEST")
    entry = _approved_facility_entry(session, facility)
    for code in ("PADER_TOWN", "PADER", "ACHOLI"):
        resolved = resolve_population(session, _unit(session, code), period_key="FY2024/25")
        assert resolved.status == "unavailable", code
        assert resolved.population is None
        assert resolved.used_facility_entry_id is None
    own = resolve_population(session, facility, period_key="FY2024/25")
    assert own.status == "ok"
    assert own.used_facility_entry_id == entry.id
    assert own.version_id is None


def test_facility_catchment_value_is_never_attributed_to_a_national_version(session):
    facility = _unit(session, "PADER_HC_III")
    pader_town = _unit(session, "PADER_TOWN")
    _approved_facility_entry(session, facility, population=2000)
    put_population(session, _unit(session, "UG"), 2024, 1_000_000, code="NATIONAL_TEST_2")
    measure_town = resolve_population(session, pader_town, period_key="FY2024/25")
    assert measure_town.version_id is None
    assert measure_town.population is None
    stored = session.scalars(select(FacilityPopulationEntry)).all()
    assert all(row.org_unit_id == facility.id for row in stored)


def test_parent_uses_one_complete_version_level_and_ignores_facility_values(session):
    acholi, pader, kitgum = _unit(session, "ACHOLI"), _unit(session, "PADER"), _unit(session, "KITGUM")
    facility = _unit(session, "PADER_HC_III")
    put_population(session, pader, 2024, 240_159, code="DISTRICT_TEST")
    put_population(session, kitgum, 2024, 239_655, code="DISTRICT_TEST")
    put_population(session, facility, 2024, 9_999, code="DISTRICT_TEST")
    resolved = resolve_population(session, acholi, period_key="FY2024/25")
    assert resolved.status == "ok"
    assert resolved.population == 240_159 + 239_655
    assert resolved.aggregation_level == "district_equivalent"
    town = resolve_population(session, _unit(session, "PADER_TOWN"), period_key="FY2024/25")
    assert town.status == "unavailable"


def test_direct_regional_population_is_not_combined_with_children(session):
    acholi, pader, kitgum = _unit(session, "ACHOLI"), _unit(session, "PADER"), _unit(session, "KITGUM")
    put_population(session, acholi, 2024, 500_000, code="MIX_TEST")
    put_population(session, pader, 2024, 240_159, code="MIX_TEST")
    put_population(session, kitgum, 2024, 239_655, code="MIX_TEST")
    resolved = resolve_population(session, acholi, period_key="FY2024/25")
    assert resolved.population == 500_000
    assert resolved.policy == "direct"


def test_national_uses_complete_district_city_cohort_when_regions_have_no_values(session):
    uganda = _unit(session, "UG")
    acholi = _unit(session, "ACHOLI")
    city = create_org_unit(session, code="GULU_CITY", name="Gulu City", level_type=OrgUnitLevel.CITY, parent=acholi)
    values = {"PADER": 240_159, "KITGUM": 239_655, "SOROTI": 100_000}
    for code, value in values.items():
        put_population(session, _unit(session, code), 2024, value, code="DC_TEST")
    incomplete = resolve_population(session, uganda, period_key="FY2024/25")
    assert incomplete.status == "unavailable"
    put_population(session, city, 2024, 233_271, code="DC_TEST")
    resolved = resolve_population(session, uganda, period_key="FY2024/25")
    assert resolved.status == "ok"
    assert resolved.population == sum(values.values()) + 233_271
    assert resolved.aggregation_level == "district_equivalent"

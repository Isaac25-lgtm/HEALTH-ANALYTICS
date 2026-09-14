"""Amendment §7 (one common numerator/denominator scope) and §8 (district/city peers)."""

from sqlalchemy import select

from app.domain.enums import OrgUnitLevel
from app.models import CalculatedValue, Indicator, IndicatorVersion, OrgUnit
from app.services.calculation import evaluate_formula, resolve_source_key, run_calculation
from app.services.geography import create_org_unit
from app.services.quality import scan_quality
from tests.helpers import put_raw


def _unit(session, code):
    return session.scalar(select(OrgUnit).where(OrgUnit.code == code))


def _eval(session, code, org):
    indicator = session.scalar(select(Indicator).where(Indicator.code == code))
    version = session.scalar(
        select(IndicatorVersion).where(
            IndicatorVersion.indicator_id == indicator.id,
            IndicatorVersion.is_current.is_(True),
        )
    )
    return evaluate_formula(
        session, org_unit=org, period="FY2024/25", version=version, programme_id=indicator.programme_id
    )


def _flags_for(session, org, code):
    run = run_calculation(
        session, org_unit=org, period="FY2024/25", user=None, programme_codes=["MNCH"], indicator_codes=[code]
    )
    value = session.scalar(select(CalculatedValue).where(CalculatedValue.calculation_run_id == run.id))
    flags = scan_quality(session, org_unit=org, period="FY2024/25", calculation_run=run)
    return value, {flag.rule_id for flag in flags if flag is not None}


def test_parent_numerator_with_child_denominator_is_unavailable(session):
    acholi, pader, kitgum = _unit(session, "ACHOLI"), _unit(session, "PADER"), _unit(session, "KITGUM")
    put_raw(session, acholi, "FY2024/25", "ANC1_FT", 40)
    put_raw(session, pader, "FY2024/25", "ANC1", 60)
    put_raw(session, kitgum, "FY2024/25", "ANC1", 40)
    measure = _eval(session, "ANC1_FIRST_TRIMESTER", acholi)
    assert measure.raw_value is None
    assert measure.reason_code == "incompatible_aggregation_scope"
    assert "No common aggregation scope" in (measure.blue_reason or "")
    value, rules = _flags_for(session, acholi, "ANC1_FIRST_TRIMESTER")
    assert value.raw_value is None
    assert value.reason_code == "incompatible_aggregation_scope"
    assert "INCOMPATIBLE_AGGREGATION_SCOPE" in rules


def test_child_numerator_with_parent_denominator_is_unavailable(session):
    acholi, pader, kitgum = _unit(session, "ACHOLI"), _unit(session, "PADER"), _unit(session, "KITGUM")
    put_raw(session, pader, "FY2024/25", "ANC1_FT", 20)
    put_raw(session, kitgum, "FY2024/25", "ANC1_FT", 20)
    put_raw(session, acholi, "FY2024/25", "ANC1", 100)
    measure = _eval(session, "ANC1_FIRST_TRIMESTER", acholi)
    assert measure.raw_value is None
    assert measure.numerator is None
    assert measure.reason_code == "incompatible_aggregation_scope"


def test_district_numerator_with_mixed_district_facility_denominator_is_unavailable(session):
    acholi, pader, kitgum = _unit(session, "ACHOLI"), _unit(session, "PADER"), _unit(session, "KITGUM")
    facility = _unit(session, "PADER_HC_III")
    put_raw(session, pader, "FY2024/25", "ANC1_FT", 20)
    put_raw(session, kitgum, "FY2024/25", "ANC1_FT", 20)
    put_raw(session, pader, "FY2024/25", "ANC1", 60)
    put_raw(session, kitgum, "FY2024/25", "ANC1", 40)
    put_raw(session, facility, "FY2024/25", "ANC1", 55)
    measure = _eval(session, "ANC1_FIRST_TRIMESTER", acholi)
    assert measure.raw_value is None
    assert measure.reason_code == "mixed_levels"
    value, rules = _flags_for(session, acholi, "ANC1_FIRST_TRIMESTER")
    assert value.raw_value is None
    assert "INCOMPATIBLE_AGGREGATION_SCOPE" in rules


def test_incompatible_mapping_versions_are_unavailable(session):
    acholi, pader, kitgum = _unit(session, "ACHOLI"), _unit(session, "PADER"), _unit(session, "KITGUM")
    for unit in (pader, kitgum):
        numerator = put_raw(session, unit, "FY2024/25", "ANC1_FT", 20)
        numerator.mapping_version = "v1"
        denominator = put_raw(session, unit, "FY2024/25", "ANC1", 50)
        denominator.mapping_version = "v2"
    session.flush()
    measure = _eval(session, "ANC1_FIRST_TRIMESTER", acholi)
    assert measure.raw_value is None
    assert measure.reason_code == "mixed_mapping_versions"
    value, rules = _flags_for(session, acholi, "ANC1_FIRST_TRIMESTER")
    assert "INCOMPATIBLE_AGGREGATION_SCOPE" in rules


def test_common_direct_scope_calculates(session):
    acholi, pader = _unit(session, "ACHOLI"), _unit(session, "PADER")
    put_raw(session, acholi, "FY2024/25", "ANC1_FT", 40)
    put_raw(session, acholi, "FY2024/25", "ANC1", 100)
    put_raw(session, pader, "FY2024/25", "ANC1_FT", 5)
    measure = _eval(session, "ANC1_FIRST_TRIMESTER", acholi)
    assert measure.raw_value == 40
    assert measure.aggregation_policy == "direct"


def test_common_child_cohort_ignores_parent_row_instead_of_mixing(session):
    acholi, pader, kitgum = _unit(session, "ACHOLI"), _unit(session, "PADER"), _unit(session, "KITGUM")
    put_raw(session, acholi, "FY2024/25", "ANC1_FT", 999)
    put_raw(session, pader, "FY2024/25", "ANC1_FT", 10)
    put_raw(session, kitgum, "FY2024/25", "ANC1_FT", 20)
    put_raw(session, pader, "FY2024/25", "ANC1", 100)
    put_raw(session, kitgum, "FY2024/25", "ANC1", 100)
    measure = _eval(session, "ANC1_FIRST_TRIMESTER", acholi)
    assert measure.numerator == 30
    assert measure.denominator == 200
    assert measure.raw_value == 15
    assert measure.aggregation_policy == "children"
    assert measure.aggregation_level == "district_equivalent"


def test_dropout_components_share_one_scope(session):
    uganda = _unit(session, "UG")
    acholi, teso = _unit(session, "ACHOLI"), _unit(session, "TESO")
    put_raw(session, uganda, "FY2024/25", "PENTA1", 100)
    put_raw(session, acholi, "FY2024/25", "PENTA3", 40)
    put_raw(session, teso, "FY2024/25", "PENTA3", 40)
    measure = _eval(session, "PENTA_DROPOUT", uganda)
    assert measure.raw_value is None
    assert measure.reason_code == "incompatible_aggregation_scope"


def _add_city(session):
    acholi = _unit(session, "ACHOLI")
    return create_org_unit(session, code="GULU_CITY", name="Gulu City", level_type=OrgUnitLevel.CITY, parent=acholi)


def test_district_and_city_siblings_aggregate_as_one_cohort(session):
    acholi, pader, kitgum = _unit(session, "ACHOLI"), _unit(session, "PADER"), _unit(session, "KITGUM")
    city = _add_city(session)
    for unit, first, total in ((pader, 10, 100), (kitgum, 20, 100), (city, 30, 100)):
        put_raw(session, unit, "FY2024/25", "ANC1_FT", first)
        put_raw(session, unit, "FY2024/25", "ANC1", total)
    resolved = resolve_source_key(session, acholi, "FY2024/25", "ANC1")
    assert resolved.status == "ok"
    assert resolved.value == 300
    assert resolved.level == "district_equivalent"
    measure = _eval(session, "ANC1_FIRST_TRIMESTER", acholi)
    assert measure.numerator == 60
    assert measure.denominator == 300
    assert measure.raw_value == 20


def test_missing_city_child_is_incomplete_not_partial_sum(session):
    acholi, pader, kitgum = _unit(session, "ACHOLI"), _unit(session, "PADER"), _unit(session, "KITGUM")
    _add_city(session)
    for unit in (pader, kitgum):
        put_raw(session, unit, "FY2024/25", "ANC1_FT", 10)
        put_raw(session, unit, "FY2024/25", "ANC1", 100)
    resolved = resolve_source_key(session, acholi, "FY2024/25", "ANC1")
    assert resolved.status == "incomplete"
    assert resolved.value is None
    measure = _eval(session, "ANC1_FIRST_TRIMESTER", acholi)
    assert measure.raw_value is None
    assert measure.reason_code == "incomplete_children"


def test_district_plus_facility_rows_are_rejected(session):
    acholi, pader, kitgum = _unit(session, "ACHOLI"), _unit(session, "PADER"), _unit(session, "KITGUM")
    facility = _unit(session, "PADER_HC_III")
    put_raw(session, kitgum, "FY2024/25", "ANC1", 100)
    put_raw(session, facility, "FY2024/25", "ANC1", 100)
    resolved = resolve_source_key(session, acholi, "FY2024/25", "ANC1")
    assert resolved.status == "mixed_levels"
    assert resolved.value is None
    del pader


def test_nested_units_of_one_class_are_not_double_counted(session):
    uganda = _unit(session, "UG")
    region = create_org_unit(
        session, code="TEST_REGION", name="Test region", level_type=OrgUnitLevel.REGION, parent=uganda
    )
    nested = create_org_unit(
        session, code="TEST_NESTED_SR", name="Nested sub-region", level_type=OrgUnitLevel.SUB_REGION, parent=region
    )
    put_raw(session, region, "FY2024/25", "ANC1", 100)
    put_raw(session, nested, "FY2024/25", "ANC1", 100)
    resolved = resolve_source_key(session, uganda, "FY2024/25", "ANC1")
    assert resolved.value is None
    assert resolved.status in {"mixed_levels", "incomplete"}


def test_parent_child_quality_scan_treats_city_as_peer_but_flags_facility_mix(session):
    acholi, pader = _unit(session, "ACHOLI"), _unit(session, "PADER")
    city = _add_city(session)
    put_raw(session, pader, "FY2024/25", "DELIVERIES", 100)
    put_raw(session, city, "FY2024/25", "DELIVERIES", 100)
    peers = scan_quality(session, org_unit=acholi, period="FY2024/25")
    assert "PARENT_CHILD_RECONCILIATION" not in {flag.rule_id for flag in peers if flag is not None}
    put_raw(session, _unit(session, "PADER_HC_III"), "FY2024/25", "DELIVERIES", 40)
    mixed = scan_quality(session, org_unit=acholi, period="FY2024/25")
    assert "PARENT_CHILD_RECONCILIATION" in {flag.rule_id for flag in mixed if flag is not None}

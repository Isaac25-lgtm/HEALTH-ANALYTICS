from sqlalchemy import select

from app.models import CalculatedValue, Indicator, IndicatorVersion, OrgUnit
from app.services.calculation import run_calculation
from tests.helpers import put_population, put_raw


def test_historical_run_not_rewritten_by_later_version(session):
    uganda = session.scalar(select(OrgUnit).where(OrgUnit.code == "UG"))
    put_population(session, uganda, 2024, 10000)
    put_raw(session, uganda, "FY2024/25", "ANC1", 500)
    run = run_calculation(
        session, org_unit=uganda, period="FY2024/25", user=None, indicator_codes=["ANC1_COVERAGE"]
    )
    assert run.config_snapshot
    original = session.scalar(
        select(CalculatedValue).where(CalculatedValue.calculation_run_id == run.id)
    )
    original_raw = float(original.raw_value)
    indicator = session.scalar(select(Indicator).where(Indicator.code == "ANC1_COVERAGE"))
    current = session.scalar(
        select(IndicatorVersion).where(
            IndicatorVersion.indicator_id == indicator.id, IndicatorVersion.is_current.is_(True)
        )
    )
    current.is_current = False
    session.add(
        IndicatorVersion(
            indicator_id=indicator.id,
            formula_version="v2-test",
            numerator_definition=current.numerator_definition,
            denominator_type=current.denominator_type,
            denominator_coefficient=0.10,
            multiplier=100,
            unit="%",
            display_precision=1,
            direction=current.direction,
            period_adjustment=True,
            formula_spec=current.formula_spec,
            classification_spec=current.classification_spec,
            aggregation_method=current.aggregation_method,
            is_current=True,
        )
    )
    session.flush()
    stored = session.scalar(
        select(CalculatedValue).where(CalculatedValue.calculation_run_id == run.id)
    )
    assert float(stored.raw_value) == original_raw
    assert stored.indicator_version_id == original.indicator_version_id
    lineage = run.config_snapshot or {}
    assert lineage.get("software_version")
    assert lineage.get("indicator_versions")
    assert lineage.get("raw_row_ids")
    assert stored.source_row_ids or lineage["raw_row_ids"]


def test_identical_inputs_are_deterministic(session):
    uganda = session.scalar(select(OrgUnit).where(OrgUnit.code == "UG"))
    put_population(session, uganda, 2024, 8000)
    put_raw(session, uganda, "FY2024/25", "ANC1", 200)
    first = run_calculation(
        session, org_unit=uganda, period="FY2024/25", user=None, indicator_codes=["ANC1_COVERAGE"]
    )
    second = run_calculation(
        session, org_unit=uganda, period="FY2024/25", user=None, indicator_codes=["ANC1_COVERAGE"]
    )
    a = session.scalar(select(CalculatedValue).where(CalculatedValue.calculation_run_id == first.id))
    b = session.scalar(select(CalculatedValue).where(CalculatedValue.calculation_run_id == second.id))
    assert float(a.raw_value) == float(b.raw_value)
    assert a.numerator == b.numerator

"""Dashboard calculation runs are reused only when every input is identical, and national and
regional screens evaluate the district/city cohort for the map and ranking."""

from uuid import UUID

from sqlalchemy import select

from app.domain.enums import AggregationClass
from app.models import CalculationRun, OrgUnit, User
from app.services.calculation import RUN_REUSE_PREFIX, run_calculation
from app.services.geography import descendants, top_units_of_class
from app.services.modules import evaluate_module
from tests.helpers import put_population, put_raw


def _unit(session, code):
    return session.scalar(select(OrgUnit).where(OrgUnit.code == code))


def _admin(session):
    return session.scalar(select(User).where(User.username == "admin.user"))


def _anc(session, unit, **kwargs):
    return evaluate_module(
        session,
        user=_admin(session),
        org_unit_id=unit.id,
        period="FY2024/25",
        module="anc",
        **kwargs,
    )


def test_identical_inputs_reuse_the_same_run(session):
    acholi = _unit(session, "ACHOLI")
    put_population(session, acholi, 2024, 1_000_000, code="REUSE_POP")
    put_raw(session, acholi, "FY2024/25", "ANC1", 48700)
    first = _anc(session, acholi, include_children=False)
    second = _anc(session, acholi, include_children=False)
    assert first["current_run_id"] == second["current_run_id"]
    run = session.get(CalculationRun, UUID(first["current_run_id"]))
    assert run.idempotency_key and run.idempotency_key.startswith(RUN_REUSE_PREFIX)


def test_a_changed_source_value_forces_a_new_run(session):
    acholi = _unit(session, "ACHOLI")
    put_population(session, acholi, 2024, 1_000_000, code="REUSE_POP")
    put_raw(session, acholi, "FY2024/25", "ANC1", 48700)
    first = _anc(session, acholi, include_children=False)
    put_raw(session, acholi, "FY2024/25", "ANC1", 48800)
    second = _anc(session, acholi, include_children=False)
    assert first["current_run_id"] != second["current_run_id"]

    def anc1(result):
        return next(row for row in result["indicators"] if row["indicator_code"] == "ANC1_COVERAGE")["raw_value"]

    assert anc1(second) > anc1(first)


def test_a_changed_population_value_forces_a_new_run(session):
    acholi = _unit(session, "ACHOLI")
    put_raw(session, acholi, "FY2024/25", "ANC1", 48700)
    put_population(session, acholi, 2024, 1_000_000, code="REUSE_POP")
    first = _anc(session, acholi, include_children=False)
    put_population(session, acholi, 2024, 500_000, code="REUSE_POP_2")
    second = _anc(session, acholi, include_children=False)
    assert first["current_run_id"] != second["current_run_id"]


def test_runs_outside_a_dashboard_batch_are_never_reused(session):
    acholi = _unit(session, "ACHOLI")
    put_raw(session, acholi, "FY2024/25", "ANC1", 48700)
    first = run_calculation(session, org_unit=acholi, period="FY2024/25", user=None, programme_codes=["MNCH"])
    second = run_calculation(session, org_unit=acholi, period="FY2024/25", user=None, programme_codes=["MNCH"])
    assert first.id != second.id
    assert first.idempotency_key is None


def test_mpdsr_event_runs_are_never_reused(session):
    uganda = _unit(session, "UG")
    first = evaluate_module(
        session, user=_admin(session), org_unit_id=uganda.id, period="FY2024/25", module="mpdsr", include_children=False
    )
    second = evaluate_module(
        session, user=_admin(session), org_unit_id=uganda.id, period="FY2024/25", module="mpdsr", include_children=False
    )
    assert first["current_run_id"] != second["current_run_id"]


def test_national_evaluation_includes_the_district_cohort(session):
    uganda = _unit(session, "UG")
    expected = {
        str(unit.id) for unit in top_units_of_class(descendants(session, uganda), AggregationClass.DISTRICT_EQUIVALENT)
    }
    assert expected, "the fixture hierarchy must contain districts"
    result = _anc(session, uganda, district_cohort=True)
    assert {row["org_unit_id"] for row in result["district_comparison"]} == expected
    assert all(row["calculation_run_id"] for row in result["district_comparison"])
    without = _anc(session, uganda)
    assert without["district_comparison"] == []

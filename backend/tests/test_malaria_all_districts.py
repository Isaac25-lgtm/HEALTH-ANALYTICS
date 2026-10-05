"""D-067: malaria vaccine values consider every district; other indicators still need a complete cohort."""

from sqlalchemy import select

from app.domain.enums import AggregationClass
from app.domain.periods import parse_period
from app.integrations.dhis2.periods import months_in
from app.models import OrgUnit, Programme, SyncJob
from app.services.calculation import run_calculation
from app.services.geography import descendants, top_units_of_class
from tests.helpers import put_population, put_raw


def _unit(session, code):
    return session.scalar(select(OrgUnit).where(OrgUnit.code == code))


def _values(session, run):
    from app.services.modules import _value_map

    return _value_map(session, run)


def test_malaria_vaccine_sums_reporting_districts_but_bcg_still_needs_all(session):
    uganda = _unit(session, "UG")
    districts = top_units_of_class(descendants(session, uganda), AggregationClass.DISTRICT_EQUIVALENT)
    assert len(districts) > 1
    put_population(session, uganda, 2024, 1_000_000, code="MV_ALL_POP")
    reporting = districts[0]
    put_raw(session, reporting, "FY2024/25", "MV1", 4_300)
    put_raw(session, reporting, "FY2024/25", "BCG", 4_300)
    programme = session.scalar(select(Programme).where(Programme.code == "EPI"))
    months = list(months_in(parse_period("FY2024/25")))
    session.add(
        SyncJob(
            job_type="aggregate",
            status="succeeded",
            programme_id=programme.id,
            org_unit_id=uganda.id,
            mapping_version="v1",
            period_from=months[0],
            period_to=months[-1],
            coverage_manifest={
                "complete": True,
                "periods": months,
                "source_keys": ["MV1"],
                "org_unit_ids": [str(unit.id) for unit in districts],
            },
        )
    )
    session.flush()
    run = run_calculation(
        session,
        org_unit=uganda,
        period="FY2024/25",
        user=None,
        programme_codes=["EPI"],
        indicator_codes=["MV1_COVERAGE", "BCG_COVERAGE"],
    )
    values = _values(session, run)
    mv1, bcg = values["MV1_COVERAGE"], values["BCG_COVERAGE"]
    # 4,300 / (1,000,000 x 4.3%) = 10%: the non-reporting districts add no doses.
    assert round(float(mv1.raw_value), 1) == 10.0
    assert mv1.aggregation_policy == "children_reporting"
    assert bcg.raw_value is None
    assert bcg.reason_code == "incomplete_children"

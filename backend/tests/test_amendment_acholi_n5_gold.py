"""Amendment §2: handoff §14.1 Acholi regressions using Appendix N.5 district/city populations.

The units below are created only for this test. Population values are the handoff's
non-production N.5 regression fixture; they are not imported production denominators.
"""

import pytest
from sqlalchemy import select

from app.domain.enums import OrgUnitLevel
from app.models import OrgUnit, User
from app.services.geography import create_org_unit
from app.services.modules import evaluate_module
from app.services.population import resolve_population
from tests.helpers import put_population, put_raw

N5_UNITS = [
    ("N5_AGAGO", "Agago", OrgUnitLevel.DISTRICT, 307_235, 314_700),
    ("N5_AMURU", "Amuru", OrgUnitLevel.DISTRICT, 247_574, 261_130),
    ("N5_GULU_CITY", "Gulu City", OrgUnitLevel.CITY, 233_271, 247_560),
    ("N5_GULU_DISTRICT", "Gulu District", OrgUnitLevel.DISTRICT, 135_373, 142_280),
    ("N5_KITGUM", "Kitgum", OrgUnitLevel.DISTRICT, 239_655, 242_410),
    ("N5_LAMWO", "Lamwo", OrgUnitLevel.DISTRICT, 213_156, 227_180),
    ("N5_NWOYA", "Nwoya", OrgUnitLevel.DISTRICT, 220_593, 242_910),
    ("N5_OMORO", "Omoro", OrgUnitLevel.DISTRICT, 207_339, 225_620),
    ("N5_PADER", "Pader", OrgUnitLevel.DISTRICT, 240_159, 248_910),
]


@pytest.fixture()
def n5_acholi(session):
    uganda = session.scalar(select(OrgUnit).where(OrgUnit.code == "UG"))
    region = create_org_unit(
        session, code="N5_ACHOLI", name="Acholi (N.5 fixture)", level_type=OrgUnitLevel.SUB_REGION, parent=uganda
    )
    for code, name, level, pop_2024, pop_2025 in N5_UNITS:
        unit = create_org_unit(session, code=code, name=name, level_type=level, parent=region)
        put_population(session, unit, 2024, pop_2024, code="N5_FIXTURE_POPULATION")
        put_population(session, unit, 2025, pop_2025, code="N5_FIXTURE_POPULATION")
    sources = {
        "FY2024/25": {"ANC1": 99_510, "DELIVERIES": 70_782},
        "FY2025/26": {
            "ANC1": 102_722,
            "DELIVERIES": 70_598,
            "FRESH_SB": 420,
            "MACERATED_SB": 464,
            "NEWBORN_DEATHS": 557,
            "MATERNAL_DEATHS": 56,
            "LIVE_BIRTHS": 69_893,
        },
    }
    for period, values in sources.items():
        for key, value in values.items():
            put_raw(session, region, period, key, value, programme_code="MNCH")
    return region


def _values(session, region, module, period):
    admin = session.scalar(select(User).where(User.username == "admin.user"))
    result = evaluate_module(
        session, user=admin, org_unit_id=region.id, period=period, module=module, include_children=False
    )
    return {row["indicator_code"]: row for row in result["indicators"]}


def test_n5_populations_come_from_complete_district_and_city_children(session, n5_acholi):
    census = resolve_population(session, n5_acholi, period_key="FY2024/25")
    projection = resolve_population(session, n5_acholi, period_key="FY2025/26")
    assert census.population == 2_044_355
    assert projection.population == 2_152_700
    assert census.aggregation_level == projection.aggregation_level == "district_equivalent"
    assert len(census.child_unit_ids) == 9


@pytest.mark.parametrize(
    ("period", "code", "numerator", "population", "coefficient", "expected"),
    [
        ("FY2024/25", "ANC1_COVERAGE", 99_510, 2_044_355, 0.05, "97.4"),
        ("FY2025/26", "ANC1_COVERAGE", 102_722, 2_152_700, 0.05, "95.4"),
        ("FY2024/25", "INSTITUTIONAL_DELIVERY", 70_782, 2_044_355, 0.0485, "71.4"),
        ("FY2025/26", "INSTITUTIONAL_DELIVERY", 70_598, 2_152_700, 0.0485, "67.6"),
    ],
)
def test_population_derived_acholi_regressions(
    session, n5_acholi, period, code, numerator, population, coefficient, expected
):
    module = "anc" if code == "ANC1_COVERAGE" else "intrapartum"
    row = _values(session, n5_acholi, module, period)[code]
    assert row["numerator"] == numerator
    assert row["denominator"] == pytest.approx(population * coefficient)
    assert row["display_value"] == expected
    assert row["population_year"] == int(period[2:6])


def test_mortality_acholi_regressions(session, n5_acholi):
    values = _values(session, n5_acholi, "intrapartum", "FY2025/26")
    assert values["PMR"]["display_value"] == "20.4"
    assert values["PMR"]["unit"] == "per 1,000 deliveries"
    assert values["MMR"]["display_value"] == "80.1"
    assert values["MMR"]["unit"] == "per 100,000 live births"

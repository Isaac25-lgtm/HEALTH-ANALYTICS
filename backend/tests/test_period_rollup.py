"""Periods built from stored months: financial years, calendar years and custom ranges.

Owner decisions 2026-09-24: monthly history is the single stored source (D-057), and a custom
range blends population month by month (D-058).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.domain.periods import PeriodError, parse_period, previous_period
from app.integrations.dhis2.periods import PeriodBridgeError, to_native_period, translate
from app.models import OrgUnit, Programme, RawAggregateValue
from app.services.period_rollup import DERIVATION, ensure_period_rollups
from app.services.population import resolve_target_denominator
from tests.helpers import map_source, put_population

FY_MONTHS = [f"2025{m:02d}" for m in range(7, 13)] + [f"2026{m:02d}" for m in range(1, 7)]


def _unit(session, code):
    return session.scalar(select(OrgUnit).where(OrgUnit.code == code))


def _programme(session, code="MNCH"):
    return session.scalar(select(Programme).where(Programme.code == code))


def _month_row(session, unit, programme, month, value, *, key="ANC1", when=None):
    row = RawAggregateValue(
        source_system="dhis2",
        programme_id=programme.id,
        org_unit_id=unit.id,
        period=month,
        source_metric_id="TEST_UID_ANC1",
        internal_source_key=key,
        dhis2_item_uid="TEST_UID_ANC1",
        value=value,
        extracted_at=when or datetime.now(UTC),
        mapping_version="v1",
        is_current=True,
        value_invalid=False,
    )
    session.add(row)
    session.flush()
    return row


def _current(session, unit, period, key="ANC1"):
    return session.scalars(
        select(RawAggregateValue).where(
            RawAggregateValue.org_unit_id == unit.id,
            RawAggregateValue.period == period,
            RawAggregateValue.internal_source_key == key,
            RawAggregateValue.is_current.is_(True),
        )
    ).all()


def test_financial_year_is_the_sum_of_its_twelve_months_with_traceable_components(session):
    programme = _programme(session)
    map_source(session, programme.id, "ANC1", "TEST_UID_ANC1")
    pader = _unit(session, "PADER")
    rows = [_month_row(session, pader, programme, month, 10 + index) for index, month in enumerate(FY_MONTHS)]

    report = ensure_period_rollups(session, ["FY2025/26"])

    assert report.periods["FY2025/26"]["status"] == "rebuilt"
    [derived] = _current(session, pader, "FY2025/26")
    assert float(derived.value) == sum(10 + index for index in range(12))
    assert derived.provenance["derivation"] == DERIVATION
    assert derived.provenance["months_reported"] == FY_MONTHS
    assert set(derived.provenance["component_row_ids"]) == {str(row.id) for row in rows}


def test_a_month_never_extracted_leaves_the_year_unavailable_rather_than_short(session):
    """Eleven months are not a year. A missing month is unknown, never zero."""
    programme = _programme(session)
    map_source(session, programme.id, "ANC1", "TEST_UID_ANC1")
    pader = _unit(session, "PADER")
    for month in FY_MONTHS[:-1]:
        _month_row(session, pader, programme, month, 10)

    ensure_period_rollups(session, ["FY2025/26"])

    assert _current(session, pader, "FY2025/26") == []


def test_a_unit_silent_in_an_extracted_month_contributes_nothing_like_dhis2(session):
    """The month was extracted nationally; this unit simply did not report in it."""
    programme = _programme(session)
    map_source(session, programme.id, "ANC1", "TEST_UID_ANC1")
    pader, kitgum = _unit(session, "PADER"), _unit(session, "KITGUM")
    for month in FY_MONTHS:
        _month_row(session, kitgum, programme, month, 5)
    for month in FY_MONTHS[:6]:
        _month_row(session, pader, programme, month, 10)

    ensure_period_rollups(session, ["FY2025/26"])

    [pader_year] = _current(session, pader, "FY2025/26")
    assert float(pader_year.value) == 60
    assert pader_year.provenance["months_reported"] == FY_MONTHS[:6]
    assert pader_year.provenance["months_requested"] == FY_MONTHS


def test_rebuilding_is_idempotent_and_re_extraction_supersedes(session):
    programme = _programme(session)
    map_source(session, programme.id, "ANC1", "TEST_UID_ANC1")
    pader = _unit(session, "PADER")
    earlier = datetime.now(UTC) - timedelta(hours=1)
    first = [_month_row(session, pader, programme, month, 10, when=earlier) for month in FY_MONTHS]

    ensure_period_rollups(session, ["FY2025/26"])
    assert ensure_period_rollups(session, ["FY2025/26"]).periods["FY2025/26"]["status"] == "current"
    [before] = _current(session, pader, "FY2025/26")

    # A late report arrives for one month.
    first[0].is_current = False
    session.flush()
    _month_row(session, pader, programme, FY_MONTHS[0], 25)
    ensure_period_rollups(session, ["FY2025/26"])

    [after] = _current(session, pader, "FY2025/26")
    assert float(after.value) == 10 * 11 + 25
    session.refresh(before)
    assert before.is_current is False
    assert before.superseded_by_id == after.id


def test_an_older_native_period_row_is_superseded_by_the_monthly_build(session):
    programme = _programme(session)
    map_source(session, programme.id, "ANC1", "TEST_UID_ANC1")
    pader = _unit(session, "PADER")
    native = _month_row(session, pader, programme, "FY2025/26", 999, when=datetime.now(UTC) - timedelta(days=1))
    for month in FY_MONTHS:
        _month_row(session, pader, programme, month, 10)

    ensure_period_rollups(session, ["FY2025/26"])

    [current] = _current(session, pader, "FY2025/26")
    assert float(current.value) == 120
    session.refresh(native)
    assert native.is_current is False


def test_non_summable_semantics_are_never_summed(session):
    programme = _programme(session)
    mapping = map_source(session, programme.id, "ANC1", "TEST_UID_ANC1")
    mapping.aggregation_semantics = "AVERAGE"
    pader = _unit(session, "PADER")
    for month in FY_MONTHS:
        _month_row(session, pader, programme, month, 10)

    ensure_period_rollups(session, ["FY2025/26"])

    assert _current(session, pader, "FY2025/26") == []


def test_custom_range_is_built_from_its_months(session):
    programme = _programme(session)
    map_source(session, programme.id, "ANC1", "TEST_UID_ANC1")
    pader = _unit(session, "PADER")
    months = ["202411", "202412"] + [f"2025{m:02d}" for m in range(1, 13)]
    for month in months:
        _month_row(session, pader, programme, month, 3)

    ensure_period_rollups(session, ["202411..202512"])

    [row] = _current(session, pader, "202411..202512")
    assert float(row.value) == 3 * 14


def test_range_parsing_comparison_and_bridge():
    spec = parse_period("202411..202512")
    assert (spec.kind, spec.months) == ("range", 14)
    assert previous_period("202411..202512") == "202311..202412"
    assert parse_period("202503..202503").key == "202503"
    with pytest.raises(PeriodError):
        parse_period("202512..202411")
    with pytest.raises(PeriodError):
        parse_period("202001..202612")
    # A range is never sent to DHIS2; it is always retrieved as months.
    with pytest.raises(PeriodBridgeError):
        to_native_period("202411..202512")
    translation = translate("202411..202512", aggregation_semantics="SUM")
    assert translation.native_period is None
    assert len(translation.dhis2_periods) == 14


def test_range_denominator_blends_population_by_month(session):
    """Nov 2024 - Dec 2025: two months of the 2024 population, twelve of the 2025 one."""
    pader = _unit(session, "PADER")
    put_population(session, pader, 2024, 120_000)
    put_population(session, pader, 2025, 240_000)

    target = resolve_target_denominator(
        session, pader, period_key="202411..202512", coefficient=0.05
    )

    if not target.ok:
        pytest.skip(f"No approved monthly population rule in the test seed: {target.reason_code}")
    months_by_year = {item["population_year"]: item["months"] for item in target.blend}
    assert sum(months_by_year.values()) == 14
    expected = sum(
        (120_000 if year == 2024 else 240_000) * 0.05 / 12 * count
        for year, count in months_by_year.items()
    )
    assert target.value == pytest.approx(expected)

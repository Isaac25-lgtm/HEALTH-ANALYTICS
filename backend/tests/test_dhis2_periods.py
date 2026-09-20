"""Regression tests for the HPIP <-> DHIS2 period bridge.

Internal period keys are not DHIS2 period identifiers. Sending one to the analytics API returns
either an error or, worse, nothing at all, which is indistinguishable from "no data" unless the
translation is pinned down by tests. The ISO formats asserted here were confirmed against the live
instance's own ``/api/periodTypes`` (DHIS2 2.41.8.1): Monthly ``yyyyMM``, Quarterly ``yyyyQn``,
SixMonthly ``yyyySn``, Yearly ``yyyy``, FinancialJuly ``yyyyJuly``.
"""

from __future__ import annotations

import pytest

from app.domain.periods import PeriodError, parse_period
from app.integrations.dhis2.periods import (
    RETRIEVAL_MONTHLY,
    RETRIEVAL_NATIVE,
    PeriodBridgeError,
    covering_internal_period,
    from_dhis2_period,
    months_in,
    to_native_period,
    translate,
)


def test_internal_financial_year_is_never_sent_literally():
    """FY2026/27 is an HPIP label. DHIS2 knows it as 2026July and nothing else."""
    translation = translate("FY2026/27")
    assert "FY2026/27" not in translation.dhis2_periods
    assert not any(period.startswith("FY") for period in translation.dhis2_periods)
    assert translation.native_period == "2026July"
    assert translation.internal_key == "FY2026/27"


@pytest.mark.parametrize(
    ("internal", "expected"),
    [
        ("202607", "202607"),
        ("2026Q1", "2026Q1"),
        ("FY2026/27Q1", "2026Q3"),  # FY Q1 is Jul-Sep, which is calendar Q3.
        ("FY2026/27Q3", "2027Q1"),  # FY Q3 is Jan-Mar of the following calendar year.
        ("2026H1", "2026S1"),
        ("2026H2", "2026S2"),
        ("2026", "2026"),
        ("FY2024/25", "2024July"),
        ("FY2026/27", "2026July"),
    ],
)
def test_every_supported_period_kind_translates_to_its_dhis2_identifier(internal, expected):
    assert to_native_period(internal) == expected


@pytest.mark.parametrize(
    ("dhis2_period", "expected_internal"),
    [
        ("202607", "202607"),
        ("2026Q3", "2026Q3"),
        ("2026S1", "2026H1"),
        ("2026July", "FY2026/27"),
        ("2024July", "FY2024/25"),
        ("2026", "2026"),
    ],
)
def test_returned_periods_normalise_back_to_internal_keys(dhis2_period, expected_internal):
    assert from_dhis2_period(dhis2_period) == expected_internal


def test_native_route_round_trips_the_requested_financial_year():
    """The response carries 2026July; calculations key on FY2026/27, so it must map back."""
    translation = translate("FY2026/27")
    assert translation.route == RETRIEVAL_NATIVE
    returned = translation.dhis2_periods[0]
    assert from_dhis2_period(returned) == translation.internal_key
    assert covering_internal_period(returned, "FY2026/27")


def test_non_summable_semantics_retrieve_months_and_stay_inside_the_year():
    """AVERAGE cannot be delegated to DHIS2: HPIP must aggregate the months under its own rule."""
    translation = translate("FY2026/27", aggregation_semantics="AVERAGE")
    assert translation.route == RETRIEVAL_MONTHLY
    assert translation.is_monthly_route
    assert len(translation.dhis2_periods) == 12
    assert translation.dhis2_periods[0] == "202607"
    assert translation.dhis2_periods[-1] == "202706"
    assert "FY2026/27" not in translation.dhis2_periods
    # Every retrieved month must belong to the requested internal period.
    assert all(covering_internal_period(p, "FY2026/27") for p in translation.dhis2_periods)


def test_summable_semantics_use_one_native_period_rather_than_twelve_requests():
    translation = translate("FY2026/27", aggregation_semantics="SUM")
    assert translation.route == RETRIEVAL_NATIVE
    assert translation.dhis2_periods == ("2026July",)


def test_months_of_a_financial_year_cross_the_calendar_boundary_in_order():
    months = months_in(parse_period("FY2026/27"))
    assert months[:2] == ("202607", "202608")
    assert months[5:7] == ("202612", "202701")
    assert len(months) == len(set(months)) == 12


def test_a_month_outside_the_requested_period_is_not_accepted():
    assert not covering_internal_period("202606", "FY2026/27")  # June 2026 is the prior FY.
    assert not covering_internal_period("202707", "FY2026/27")  # July 2027 is the next FY.
    assert covering_internal_period("202706", "FY2026/27")


def test_unknown_dhis2_period_is_rejected_rather_than_guessed():
    for bad in ("FY2026/27", "2026July1", "", "202613", "Q3"):
        with pytest.raises(PeriodBridgeError):
            from_dhis2_period(bad)


def test_unparseable_internal_period_is_rejected_before_any_translation():
    """PeriodBridgeError extends PeriodError, so callers can catch the base for either failure."""
    with pytest.raises(PeriodError):
        to_native_period("not-a-period")
    assert issubclass(PeriodBridgeError, PeriodError)

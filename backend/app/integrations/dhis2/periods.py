"""Canonical bridge between HPIP analysis periods and DHIS2 ISO periods.

HPIP period keys are internal (``FY2026/27``, ``FY2026/27Q1``, ``2026H1``). DHIS2 has its own ISO
period identifiers and rejects the internal spelling outright, so every request must translate and
every response must translate back. Sending ``FY2026/27`` to the analytics API is always a defect.

Retrieval policy
----------------
Two routes are supported, and the choice is a property of the approved mapping rather than a
per-call convenience:

``native``
    One DHIS2 period whose boundaries match the internal period exactly, letting DHIS2 aggregate
    with the data element's own aggregation type. Used when the approved internal semantics is
    ``SUM`` for a period-summable count, which is what DHIS2 does natively for such elements.

``monthly``
    The constituent months, aggregated inside HPIP under the approved mapping semantics. Required
    whenever the internal semantics is not plain summation (``AVERAGE``, ``LAST``), because
    delegating those to DHIS2 would silently apply the upstream element's rule instead of the
    approved one.

Both routes record every upstream period in provenance: the internal key is never lost, and the
caller can always show which months a value was built from.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date

from app.domain.periods import PeriodError, PeriodSpec, parse_period

# DHIS2 ISO period spellings this bridge understands.
_DHIS2_MONTH_RE = re.compile(r"^(\d{4})(0[1-9]|1[0-2])$")
_DHIS2_QUARTER_RE = re.compile(r"^(\d{4})Q([1-4])$")
_DHIS2_SIXMONTH_RE = re.compile(r"^(\d{4})S([12])$")
_DHIS2_FINANCIAL_JULY_RE = re.compile(r"^(\d{4})July$")
_DHIS2_YEAR_RE = re.compile(r"^(\d{4})$")

# Internal semantics that DHIS2 reproduces exactly when a native period is requested.
_NATIVE_SAFE_SEMANTICS = {"SUM", "COUNT"}

RETRIEVAL_NATIVE = "native"
RETRIEVAL_MONTHLY = "monthly"


class PeriodBridgeError(PeriodError):
    """The internal period cannot be expressed as a DHIS2 period."""


@dataclass(frozen=True)
class PeriodTranslation:
    """How one internal period is retrieved from DHIS2, and how to get back."""

    internal_key: str
    route: str
    dhis2_periods: tuple[str, ...]
    native_period: str | None

    @property
    def is_monthly_route(self) -> bool:
        return self.route == RETRIEVAL_MONTHLY


def months_in(spec: PeriodSpec) -> tuple[str, ...]:
    """Every calendar month covered by the internal period, as DHIS2 monthly identifiers."""
    months: list[str] = []
    year, month = spec.start.year, spec.start.month
    while (year, month) <= (spec.end.year, spec.end.month):
        months.append(f"{year}{month:02d}")
        month += 1
        if month > 12:
            month = 1
            year += 1
    return tuple(months)


def to_native_period(key: str) -> str:
    """The single DHIS2 period identifier matching this internal period exactly.

    Raises if no DHIS2 period type has the same boundaries, rather than returning an approximation.
    """
    spec = parse_period(key)
    if spec.kind == "month":
        return f"{spec.start.year}{spec.start.month:02d}"
    if spec.kind == "quarter":
        return f"{spec.start.year}Q{((spec.start.month - 1) // 3) + 1}"
    if spec.kind == "fy_quarter":
        # A financial-year quarter is an ordinary calendar quarter; only its label differs.
        return f"{spec.start.year}Q{((spec.start.month - 1) // 3) + 1}"
    if spec.kind == "half":
        return f"{spec.start.year}S{1 if spec.start.month == 1 else 2}"
    if spec.kind == "year":
        return str(spec.start.year)
    if spec.kind == "fy":
        # Uganda's financial year starts in July, which DHIS2 spells <start-year>July.
        return f"{spec.start.year}July"
    raise PeriodBridgeError(f"No DHIS2 period type matches internal period kind {spec.kind!r}.")


def translate(key: str, *, aggregation_semantics: str | None = None) -> PeriodTranslation:
    """Decide how to retrieve one internal period, honouring approved aggregation semantics."""
    spec = parse_period(key)
    native = to_native_period(spec.key)
    semantics = (aggregation_semantics or "SUM").strip().upper()
    if spec.kind == "month" or semantics in _NATIVE_SAFE_SEMANTICS:
        # A month is already a single DHIS2 period, so there is nothing for HPIP to aggregate.
        return PeriodTranslation(
            internal_key=spec.key,
            route=RETRIEVAL_NATIVE,
            dhis2_periods=(native,),
            native_period=native,
        )
    # AVERAGE, LAST and anything else must be computed by HPIP from the months themselves.
    return PeriodTranslation(
        internal_key=spec.key,
        route=RETRIEVAL_MONTHLY,
        dhis2_periods=months_in(spec),
        native_period=native,
    )


def from_dhis2_period(value: str) -> str:
    """Normalise a DHIS2 period identifier back to its internal HPIP key.

    Responses carry DHIS2 spellings. Calculations key on internal periods, so every returned period
    must map back deterministically or be rejected.
    """
    raw = (value or "").strip()
    match = _DHIS2_MONTH_RE.match(raw)
    if match:
        return f"{match.group(1)}{match.group(2)}"
    match = _DHIS2_QUARTER_RE.match(raw)
    if match:
        return f"{match.group(1)}Q{match.group(2)}"
    match = _DHIS2_SIXMONTH_RE.match(raw)
    if match:
        return f"{match.group(1)}H{match.group(2)}"
    match = _DHIS2_FINANCIAL_JULY_RE.match(raw)
    if match:
        start_year = int(match.group(1))
        return f"FY{start_year}/{str(start_year + 1)[2:]}"
    match = _DHIS2_YEAR_RE.match(raw)
    if match:
        return match.group(1)
    raise PeriodBridgeError(f"Unrecognised DHIS2 period identifier: {value!r}")


def covering_internal_period(dhis2_period: str, internal_key: str) -> bool:
    """Whether a returned DHIS2 period belongs to the internal period that was requested.

    On the monthly route the response carries months, not the internal key, so equality alone would
    reject every row. Containment is checked against the internal period's own boundaries.
    """
    spec = parse_period(internal_key)
    raw = (dhis2_period or "").strip()
    match = _DHIS2_MONTH_RE.match(raw)
    if match:
        month_start = date(int(match.group(1)), int(match.group(2)), 1)
        return spec.start <= month_start <= spec.end
    try:
        return from_dhis2_period(raw) == spec.key
    except PeriodBridgeError:
        return False


def month_end(period: str) -> date:
    """Last day of a DHIS2 monthly identifier, for provenance windows."""
    match = _DHIS2_MONTH_RE.match((period or "").strip())
    if not match:
        raise PeriodBridgeError(f"Not a DHIS2 monthly period: {period!r}")
    year, month = int(match.group(1)), int(match.group(2))
    return date(year, month, calendar.monthrange(year, month)[1])

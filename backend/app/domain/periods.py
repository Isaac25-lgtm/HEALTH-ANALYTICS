"""Canonical analysis-period parsing. Uganda FY is July–June."""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta


class PeriodError(ValueError):
    pass


@dataclass(frozen=True)
class PeriodSpec:
    key: str
    kind: str
    months: int
    start: date
    end: date
    parent_fy: str | None = None

    @property
    def fraction_of_year(self) -> float:
        return self.months / 12


_FY_RE = re.compile(r"^FY(\d{4})/(\d{2}|\d{4})$", re.IGNORECASE)
_FY_QUARTER_RE = re.compile(r"^FY(\d{4})/(\d{2}|\d{4})Q([1-4])$", re.IGNORECASE)
_QUARTER_RE = re.compile(r"^(\d{4})Q([1-4])$", re.IGNORECASE)
_HALF_RE = re.compile(r"^(\d{4})(?:H|S)([12])$", re.IGNORECASE)
_MONTH_RE = re.compile(r"^(\d{4})[-]?(\d{2})$")
_YEAR_RE = re.compile(r"^(\d{4})$")
# A custom month range, inclusive at both ends: 202411..202512 is Nov 2024 to Dec 2025.
_RANGE_RE = re.compile(r"^(\d{4})(\d{2})\.\.(\d{4})(\d{2})$")
# Longest range accepted, so an accidental request cannot ask for decades of months.
MAX_RANGE_MONTHS = 72


def uganda_fy_key(value: date) -> str:
    start_year = value.year if value.month >= 7 else value.year - 1
    return f"FY{start_year}/{str(start_year + 1)[2:]}"


def _fy_bounds(start_year: int) -> tuple[date, date, str]:
    start = date(start_year, 7, 1)
    end = date(start_year + 1, 6, 30)
    return start, end, f"FY{start_year}/{str(start_year + 1)[2:]}"


def range_key(start: date, end: date) -> str:
    return f"{start.year}{start.month:02d}..{end.year}{end.month:02d}"


def parse_period(key: str) -> PeriodSpec:
    raw = key.strip()
    match = _RANGE_RE.match(raw)
    if match:
        start_year, start_month = int(match.group(1)), int(match.group(2))
        end_year, end_month = int(match.group(3)), int(match.group(4))
        if not (1 <= start_month <= 12 and 1 <= end_month <= 12):
            raise PeriodError(f"Invalid month in range {key}")
        start = date(start_year, start_month, 1)
        end = date(end_year, end_month, calendar.monthrange(end_year, end_month)[1])
        if end < start:
            raise PeriodError(f"Range {key} ends before it starts")
        months = (end_year - start_year) * 12 + (end_month - start_month) + 1
        if months > MAX_RANGE_MONTHS:
            raise PeriodError(f"Range {key} spans {months} months; the maximum is {MAX_RANGE_MONTHS}")
        # A one-month range is simply that month, so it keeps a single canonical spelling.
        if months == 1:
            return parse_period(f"{start_year}{start_month:02d}")
        return PeriodSpec(
            key=range_key(start, end),
            kind="range",
            months=months,
            start=start,
            end=end,
            parent_fy=uganda_fy_key(start),
        )
    match = _FY_QUARTER_RE.match(raw)
    if match:
        start_year = int(match.group(1))
        quarter = int(match.group(3))
        _, _, fy_key = _fy_bounds(start_year)
        start_month = 7 + (quarter - 1) * 3
        year = start_year if start_month <= 12 else start_year + 1
        month = start_month if start_month <= 12 else start_month - 12
        start = date(year, month, 1)
        end_month = month + 2
        end_year = year
        if end_month > 12:
            end_month -= 12
            end_year += 1
        end = date(end_year, end_month, calendar.monthrange(end_year, end_month)[1])
        return PeriodSpec(
            key=f"{fy_key}Q{quarter}",
            kind="fy_quarter",
            months=3,
            start=start,
            end=end,
            parent_fy=fy_key,
        )

    match = _FY_RE.match(raw)
    if match:
        start_year = int(match.group(1))
        start, end, fy_key = _fy_bounds(start_year)
        return PeriodSpec(key=fy_key, kind="fy", months=12, start=start, end=end, parent_fy=fy_key)

    match = _QUARTER_RE.match(raw)
    if match:
        year = int(match.group(1))
        quarter = int(match.group(2))
        start_month = (quarter - 1) * 3 + 1
        start = date(year, start_month, 1)
        end_month = start_month + 2
        end = date(year, end_month, calendar.monthrange(year, end_month)[1])
        return PeriodSpec(
            key=f"{year}Q{quarter}",
            kind="quarter",
            months=3,
            start=start,
            end=end,
            parent_fy=uganda_fy_key(start),
        )

    match = _HALF_RE.match(raw)
    if match:
        year = int(match.group(1))
        half = int(match.group(2))
        start_month = 1 if half == 1 else 7
        start = date(year, start_month, 1)
        end_month = 6 if half == 1 else 12
        end = date(year, end_month, calendar.monthrange(year, end_month)[1])
        return PeriodSpec(
            key=f"{year}H{half}",
            kind="half",
            months=6,
            start=start,
            end=end,
            parent_fy=uganda_fy_key(start),
        )

    match = _MONTH_RE.match(raw)
    if match:
        year = int(match.group(1))
        month = int(match.group(2))
        if month < 1 or month > 12:
            raise PeriodError(f"Invalid month in period {key}")
        start = date(year, month, 1)
        end = date(year, month, calendar.monthrange(year, month)[1])
        return PeriodSpec(
            key=f"{year}{month:02d}",
            kind="month",
            months=1,
            start=start,
            end=end,
            parent_fy=uganda_fy_key(start),
        )

    match = _YEAR_RE.match(raw)
    if match:
        year = int(match.group(1))
        start = date(year, 1, 1)
        end = date(year, 12, 31)
        return PeriodSpec(
            key=str(year),
            kind="year",
            months=12,
            start=start,
            end=end,
            parent_fy=uganda_fy_key(date(year, 7, 1)),
        )

    raise PeriodError(f"Unrecognised period key: {key}")


def date_in_period(value: date, spec: PeriodSpec) -> bool:
    return spec.start <= value <= spec.end


def days_between(start: date, end: date) -> int:
    return (end - start).days


def add_days(value: date, days: int) -> date:
    return value + timedelta(days=days)


def previous_period(key: str) -> str:
    spec = parse_period(key)
    if spec.kind == "fy":
        start_year = spec.start.year - 1
        return f"FY{start_year}/{str(start_year + 1)[2:]}"
    if spec.kind == "fy_quarter":
        quarter = int(spec.key[-1])
        if quarter == 1:
            return f"{previous_period(spec.parent_fy)}Q4"
        return f"{spec.parent_fy}Q{quarter - 1}"
    if spec.kind == "quarter":
        year = spec.start.year
        quarter = ((spec.start.month - 1) // 3) + 1
        if quarter == 1:
            return f"{year - 1}Q4"
        return f"{year}Q{quarter - 1}"
    if spec.kind == "month":
        month = spec.start.month - 1
        year = spec.start.year
        if month == 0:
            month = 12
            year -= 1
        return f"{year}{month:02d}"
    if spec.kind == "year":
        return str(spec.start.year - 1)
    if spec.kind == "half":
        half = 1 if spec.start.month == 1 else 2
        if half == 1:
            return f"{spec.start.year - 1}H2"
        return f"{spec.start.year}H1"
    if spec.kind == "range":
        # The same calendar window one year earlier, so a Nov-Dec range is compared with the
        # previous Nov-Dec rather than with the months immediately before it.
        start = date(spec.start.year - 1, spec.start.month, 1)
        end = date(spec.end.year - 1, spec.end.month, 1)
        return range_key(start, end)
    raise PeriodError(f"Cannot derive a previous period for {key}")


def trend_periods(key: str, count: int = 6) -> list[str]:
    current = parse_period(key).key
    series = [current]
    while len(series) < count:
        current = previous_period(current)
        series.append(current)
    return list(reversed(series))


def trend_window(key: str, today: date | None = None) -> list[str]:
    """The monthly points a trend chart shows for a period, oldest first.

    A multi-month period (financial year, quarter, half, calendar year or custom range) trends
    across its own months, as the reference screens do (Jul to Jun). A single month trends across
    the twelve months ending with it. Months after the last closed month are left out, so an
    in-progress year shows only what has actually been reported.
    """
    spec = parse_period(key)
    today = today or date.today()
    last_closed = date(today.year, today.month, 1) - timedelta(days=1)
    if spec.kind == "month":
        end = spec.start
        start_year, start_month = end.year, end.month - 11
        while start_month < 1:
            start_month += 12
            start_year -= 1
        start = date(start_year, start_month, 1)
    else:
        start, end = spec.start, spec.end
    months: list[str] = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        if date(year, month, 1) <= last_closed:
            months.append(f"{year}{month:02d}")
        month += 1
        if month > 12:
            month, year = 1, year + 1
    return months

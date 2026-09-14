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


def uganda_fy_key(value: date) -> str:
    start_year = value.year if value.month >= 7 else value.year - 1
    return f"FY{start_year}/{str(start_year + 1)[2:]}"


def _fy_bounds(start_year: int) -> tuple[date, date, str]:
    start = date(start_year, 7, 1)
    end = date(start_year + 1, 6, 30)
    return start, end, f"FY{start_year}/{str(start_year + 1)[2:]}"


def parse_period(key: str) -> PeriodSpec:
    raw = key.strip()
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
    raise PeriodError(f"Cannot derive a previous period for {key}")


def trend_periods(key: str, count: int = 6) -> list[str]:
    current = parse_period(key).key
    series = [current]
    while len(series) < count:
        current = previous_period(current)
        series.append(current)
    return list(reversed(series))

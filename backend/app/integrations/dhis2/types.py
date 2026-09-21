from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


@dataclass(frozen=True)
class AggregateObservation:
    org_unit_uid: str
    period: str
    item_uid: str
    value: float | None
    category_option_combo_uid: str | None = None
    source_freshness_at: datetime | None = None
    absence_reason: str | None = None
    payload_checksum: str | None = None
    value_invalid: bool = False
    source_periods: tuple[str, ...] = ()


@dataclass(frozen=True)
class EventObservation:
    event_uid: str
    source_connector: str
    program_uid: str | None
    program_stage_uid: str | None
    org_unit_uid: str
    status: str
    occurred_at: datetime | None
    completed_at: datetime | None
    source_created_at: datetime | None
    source_updated_at: datetime | None
    data_values: dict[str, Any] = field(default_factory=dict)
    source_freshness_at: datetime | None = None


@dataclass(frozen=True)
class EventAggregateObservation:
    org_unit_uid: str
    period: str
    metric: str
    value: float | None
    source_freshness_at: datetime | None = None
    source_periods: tuple[str, ...] = ()


@dataclass
class ConnectorPage:
    items: list
    page: int
    page_count: int | None
    has_more: bool


def parse_optional_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def parse_optional_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None

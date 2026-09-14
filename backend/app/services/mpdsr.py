from __future__ import annotations

from datetime import date

from app.domain.enums import ACTIVE_NOT_COMPLETED_LABEL, EventStatus
from app.domain.periods import parse_period
from app.models import RawEventSnapshot


def event_display_status(status: str) -> str:
    if status == EventStatus.ACTIVE.value:
        return ACTIVE_NOT_COMPLETED_LABEL
    return status


def is_completed(event: RawEventSnapshot) -> bool:
    return event.status == EventStatus.COMPLETED.value


def notification_timely(death: date, notification: date) -> bool:
    delta = (notification - death).days
    return 0 <= delta <= 1


def review_timely(death: date, review: date) -> bool:
    delta = (review - death).days
    return 0 <= delta <= 7


def chronology_valid_notification(death: date | None, notification: date | None) -> bool:
    if death is None or notification is None:
        return False
    return notification >= death


def chronology_valid_review(death: date | None, review: date | None) -> bool:
    if death is None or review is None:
        return False
    return review >= death


def in_death_cohort(event: RawEventSnapshot, period_key: str) -> bool:
    if event.death_date is None:
        return False
    spec = parse_period(period_key)
    return spec.start <= event.death_date <= spec.end

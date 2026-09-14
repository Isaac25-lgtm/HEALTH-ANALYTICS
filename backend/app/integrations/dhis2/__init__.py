"""DHIS2 connector boundary. Live calls require authorised configuration."""

from app.config import get_settings
from app.integrations.dhis2.aggregate import AggregateAnalyticsAdapter
from app.integrations.dhis2.event_analytics import EventAnalyticsAdapter
from app.integrations.dhis2.http import Dhis2HttpClient
from app.integrations.dhis2.tracker import TrackerEventsAdapter


def configured_base_url() -> str:
    return get_settings().dhis2_base_url


def is_configured() -> bool:
    settings = get_settings()
    if not settings.dhis2_base_url:
        return False
    if settings.dhis2_auth_method == "pat":
        return bool(settings.dhis2_pat)
    return bool(settings.dhis2_username)


def dhis2_readiness_status() -> str:
    if not is_configured():
        return "not_configured"
    return "configured_unverified"


__all__ = [
    "AggregateAnalyticsAdapter",
    "Dhis2HttpClient",
    "EventAnalyticsAdapter",
    "TrackerEventsAdapter",
    "configured_base_url",
    "dhis2_readiness_status",
    "is_configured",
]

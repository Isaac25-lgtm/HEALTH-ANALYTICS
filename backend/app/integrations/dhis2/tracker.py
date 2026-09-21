from __future__ import annotations

from dataclasses import dataclass, field

from app.integrations.dhis2.errors import Dhis2CancelledError, Dhis2ValidationError
from app.integrations.dhis2.http import Dhis2HttpClient
from app.integrations.dhis2.types import EventObservation, parse_optional_datetime


@dataclass
class TrackerFetchResult:
    observations: list[EventObservation] = field(default_factory=list)
    page_limit_reached: bool = False
    pages_fetched: int = 0


class TrackerEventsAdapter:
    def __init__(self, client: Dhis2HttpClient) -> None:
        self.client = client
        self.last_result = TrackerFetchResult()

    def fetch_events(
        self,
        *,
        program_uid: str,
        org_unit_uids: list[str],
        program_stage_uid: str | None = None,
        occurred_after: str | None = None,
        occurred_before: str | None = None,
        page_size: int | None = None,
        ou_mode: str | None = None,
    ) -> list[EventObservation]:
        result = self.fetch_events_result(
            program_uid=program_uid,
            org_unit_uids=org_unit_uids,
            program_stage_uid=program_stage_uid,
            occurred_after=occurred_after,
            occurred_before=occurred_before,
            page_size=page_size,
            ou_mode=ou_mode,
        )
        return result.observations

    def fetch_events_result(
        self,
        *,
        program_uid: str,
        org_unit_uids: list[str],
        program_stage_uid: str | None = None,
        occurred_after: str | None = None,
        occurred_before: str | None = None,
        page_size: int | None = None,
        ou_mode: str | None = None,
    ) -> TrackerFetchResult:
        prefix = self.client.settings.dhis2_api_path_prefix.rstrip("/")
        size = page_size or self.client.settings.dhis2_page_size
        mode = ou_mode or self.client.settings.dhis2_ou_mode or "DESCENDANTS"
        collected: list[EventObservation] = []
        page_limit = False
        pages = 0
        targets = org_unit_uids or [None]
        # The service supplies non-overlapping district/city peers for a broad scope. Tracker
        # accepts one orgUnit per request, so query each peer with the requested mode; switching
        # to SELECTED here would silently omit events recorded below the district/city.
        effective_mode = mode
        for org_unit_uid in targets:
            page = 1
            while True:
                if self.client._cancelled():
                    raise Dhis2CancelledError()
                params = {
                    "program": program_uid,
                    "page": page,
                    "pageSize": size,
                    "totalPages": "true",
                    "ouMode": effective_mode,
                }
                if org_unit_uid:
                    params["orgUnit"] = org_unit_uid
                if program_stage_uid:
                    params["programStage"] = program_stage_uid
                if occurred_after:
                    params["occurredAfter"] = occurred_after
                if occurred_before:
                    params["occurredBefore"] = occurred_before
                payload = self.client.get_json(f"{prefix}/tracker/events", params=params)
                rows = parse_tracker_events(payload)
                collected.extend(rows)
                pages += 1
                pager = payload.get("pager") or {}
                page_count = int(pager.get("pageCount") or 1) if pager else 1
                if page >= page_count or not rows:
                    break
                page += 1
                if page > self.client.settings.dhis2_max_pages:
                    page_limit = True
                    break
            if page_limit:
                break
        self.last_result = TrackerFetchResult(
            observations=collected, page_limit_reached=page_limit, pages_fetched=pages
        )
        return self.last_result


def parse_tracker_events(payload: dict | list) -> list[EventObservation]:
    if isinstance(payload, list):
        instances = payload
    elif isinstance(payload, dict):
        if "instances" in payload:
            instances = payload["instances"]
        elif "events" in payload:
            instances = payload["events"]
        else:
            raise Dhis2ValidationError("Tracker payload missing instances/events.")
    else:
        raise Dhis2ValidationError("Tracker payload must be an object or list.")
    if not isinstance(instances, list):
        raise Dhis2ValidationError("Tracker instances must be a list.")
    observations: list[EventObservation] = []
    for item in instances:
        if not isinstance(item, dict):
            continue
        observations.append(_map_tracker_event(item))
    return observations


def _map_tracker_event(item: dict) -> EventObservation:
    data_values = {}
    raw_values = item.get("dataValues") or []
    if isinstance(raw_values, list):
        for entry in raw_values:
            if not isinstance(entry, dict):
                continue
            de = entry.get("dataElement")
            if de:
                data_values[str(de)] = entry.get("value")
    status = str(item.get("status") or "ACTIVE")
    return EventObservation(
        event_uid=str(item.get("event") or item.get("eventUid") or ""),
        source_connector="tracker",
        program_uid=item.get("program"),
        program_stage_uid=item.get("programStage"),
        org_unit_uid=str(item.get("orgUnit") or ""),
        status=status,
        occurred_at=parse_optional_datetime(item.get("occurredAt") or item.get("eventDate")),
        completed_at=parse_optional_datetime(item.get("completedAt")),
        source_created_at=parse_optional_datetime(item.get("createdAt")),
        source_updated_at=parse_optional_datetime(item.get("updatedAt")),
        data_values=data_values,
    )

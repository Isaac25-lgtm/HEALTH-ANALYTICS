from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date

from app.integrations.dhis2.errors import Dhis2CancelledError, Dhis2ValidationError
from app.integrations.dhis2.http import Dhis2HttpClient
from app.integrations.dhis2.types import EventObservation, parse_optional_datetime


@dataclass
class TrackerFetchResult:
    observations: list[EventObservation] = field(default_factory=list)
    page_limit_reached: bool = False
    pages_fetched: int = 0


def _occurred_bound(value: str, *, end: bool = False) -> str:
    """Make an approved date window explicit; preserve timestamp callers verbatim."""
    if len(value) != 10:
        return value
    try:
        day = date.fromisoformat(value)
    except ValueError as exc:
        raise Dhis2ValidationError("Tracker date boundary is invalid.") from exc
    return day.isoformat() + ("T23:59:59.999" if end else "T00:00:00.000")


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
        allowed_data_element_uids: set[str] | None = None,
    ) -> TrackerFetchResult:
        prefix = self.client.settings.dhis2_api_path_prefix.rstrip("/")
        size = page_size or self.client.settings.dhis2_page_size
        mode = ou_mode or self.client.settings.dhis2_ou_mode or "DESCENDANTS"
        max_pages = self.client.settings.dhis2_max_pages
        targets = org_unit_uids or [None]
        stop = threading.Event()

        # The service supplies non-overlapping district/city peers for a broad scope. Tracker
        # accepts one orgUnit per request, so query each peer with the requested mode; switching
        # to SELECTED here would silently omit events recorded below the district/city.
        def fetch_peer(org_unit_uid: str | None) -> tuple[list[EventObservation], int, bool]:
            collected: list[EventObservation] = []
            pages = 0
            page = 1
            while True:
                if stop.is_set() or self.client._cancelled():
                    raise Dhis2CancelledError()
                # The total page count is not requested: counting every matching event is the slow
                # part of a tracker query. A page shorter than the page size is the last one.
                params = {
                    "program": program_uid,
                    "page": page,
                    "pageSize": size,
                    "ouMode": mode,
                }
                if org_unit_uid:
                    params["orgUnit"] = org_unit_uid
                if program_stage_uid:
                    params["programStage"] = program_stage_uid
                if occurred_after:
                    params["occurredAfter"] = _occurred_bound(occurred_after)
                if occurred_before:
                    params["occurredBefore"] = _occurred_bound(occurred_before, end=True)
                payload = self.client.get_json(f"{prefix}/tracker/events", params=params)
                rows = parse_tracker_events(payload, allowed_data_element_uids=allowed_data_element_uids)
                collected.extend(rows)
                pages += 1
                pager = (payload.get("pager") or {}) if isinstance(payload, dict) else {}
                page_count = pager.get("pageCount") or (payload.get("pageCount") if isinstance(payload, dict) else None)
                if not rows:
                    break
                if page_count is not None:
                    if page >= int(page_count):
                        break
                elif len(rows) < size:
                    break
                page += 1
                if page > max_pages:
                    return collected, pages, True
            return collected, pages, False

        workers = max(1, min(int(getattr(self.client.settings, "dhis2_tracker_parallel_requests", 1)), len(targets)))
        results: list[tuple[list[EventObservation], int, bool]] = []
        if workers == 1:
            for target in targets:
                result = fetch_peer(target)
                results.append(result)
                if result[2]:
                    break
        else:
            # The cancellation check reads the job through the caller's database session, which must
            # not be used by two threads at once: the workers take turns to ask.
            check_cancelled = self.client._cancelled
            check_lock = threading.Lock()

            def check_in_turn() -> bool:
                with check_lock:
                    return check_cancelled()

            self.client._cancelled = check_in_turn
            try:
                with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="tracker-events") as pool:
                    try:
                        # map() keeps the peers in request order, so the extraction is deterministic.
                        results = list(pool.map(fetch_peer, targets))
                    except BaseException:
                        stop.set()
                        raise
            finally:
                self.client._cancelled = check_cancelled
        collected = [row for rows, _pages, _limit in results for row in rows]
        self.last_result = TrackerFetchResult(
            observations=collected,
            page_limit_reached=any(limit for _rows, _pages, limit in results),
            pages_fetched=sum(pages for _rows, pages, _limit in results),
        )
        return self.last_result


def parse_tracker_events(
    payload: dict | list, *, allowed_data_element_uids: set[str] | None = None
) -> list[EventObservation]:
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
        observations.append(_map_tracker_event(item, allowed_data_element_uids))
    return observations


def _map_tracker_event(item: dict, allowed_data_element_uids: set[str] | None = None) -> EventObservation:
    data_values = {}
    raw_values = item.get("dataValues") or []
    if isinstance(raw_values, list):
        for entry in raw_values:
            if not isinstance(entry, dict):
                continue
            de = entry.get("dataElement")
            if de and (allowed_data_element_uids is None or str(de) in allowed_data_element_uids):
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

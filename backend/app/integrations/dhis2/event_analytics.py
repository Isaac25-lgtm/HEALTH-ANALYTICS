from __future__ import annotations

from app.integrations.dhis2.errors import Dhis2CancelledError, Dhis2ValidationError
from app.integrations.dhis2.http import Dhis2HttpClient
from app.integrations.dhis2.types import (
    EventAggregateObservation,
    EventObservation,
    parse_optional_datetime,
)


class EventAnalyticsAdapter:
    def __init__(self, client: Dhis2HttpClient) -> None:
        self.client = client
        self.page_limit_reached = False

    def query_events(
        self,
        *,
        program_uid: str,
        org_unit_uids: list[str],
        periods: list[str] | None = None,
        dimensions: list[str] | None = None,
        page_size: int | None = None,
    ) -> list[EventObservation]:
        prefix = self.client.settings.dhis2_api_path_prefix.rstrip("/")
        size = page_size or self.client.settings.dhis2_page_size
        page = 1
        collected: list[EventObservation] = []
        while True:
            if self.client._cancelled():
                raise Dhis2CancelledError()
            params: dict = {
                "dimension": [f"ou:{';'.join(org_unit_uids)}"],
                "page": page,
                "pageSize": size,
                "outputType": "EVENT",
            }
            if periods:
                params["dimension"].append(f"pe:{';'.join(periods)}")
            if dimensions:
                params["dimension"].extend(dimensions)
            payload = self.client.get_json(
                f"{prefix}/analytics/events/query/{program_uid}",
                params=params,
            )
            rows = parse_event_query_rows(payload, program_uid)
            collected.extend(rows)
            pager = None
            metadata = payload.get("metaData")
            if isinstance(metadata, dict):
                pager = metadata.get("pager")
            if pager and isinstance(pager, dict):
                page_count = int(pager.get("pageCount") or 1)
                if page >= page_count or not rows:
                    break
            elif len(rows) < size:
                break
            page += 1
            if page > self.client.settings.dhis2_max_pages:
                self.page_limit_reached = True
                break
        return collected

    def aggregate(
        self,
        *,
        program_uid: str,
        org_unit_uids: list[str],
        periods: list[str],
        output_uid: str | None = None,
    ) -> list[EventAggregateObservation]:
        prefix = self.client.settings.dhis2_api_path_prefix.rstrip("/")
        params = {
            "dimension": [
                f"ou:{';'.join(org_unit_uids)}",
                f"pe:{';'.join(periods)}",
            ]
        }
        if output_uid:
            params["dimension"].append(f"dx:{output_uid}")
        payload = self.client.get_json(
            f"{prefix}/analytics/events/aggregate/{program_uid}",
            params=params,
        )
        return parse_event_aggregate_rows(payload)


def parse_event_query_rows(payload: dict, program_uid: str) -> list[EventObservation]:
    headers = payload.get("headers")
    rows = payload.get("rows")
    if headers is None or rows is None:
        raise Dhis2ValidationError("Event Analytics query payload missing headers/rows.")
    names = [str(item.get("name") or item.get("column")) for item in headers if isinstance(item, dict)]
    index = {name: i for i, name in enumerate(names)}
    if "event" not in index or "ou" not in index:
        raise Dhis2ValidationError("Event Analytics query must include event and ou columns.")
    freshness = parse_optional_datetime(str(payload.get("headerUniq") or "") or None)
    observations: list[EventObservation] = []
    for row in rows:
        if not isinstance(row, list):
            continue
        data_values = {}
        for name, i in index.items():
            if name in {"event", "ou", "ouname", "psi", "ps", "programstatus", "eventstatus", "eventdate"}:
                continue
            if i < len(row):
                data_values[name] = row[i]
        status = str(row[index["eventstatus"]]) if "eventstatus" in index else "ACTIVE"
        observations.append(
            EventObservation(
                event_uid=str(row[index["event"]]),
                source_connector="event_analytics_query",
                program_uid=program_uid,
                program_stage_uid=str(row[index["ps"]]) if "ps" in index else None,
                org_unit_uid=str(row[index["ou"]]),
                status=status,
                occurred_at=parse_optional_datetime(str(row[index["eventdate"]])) if "eventdate" in index else None,
                completed_at=None,
                source_created_at=None,
                source_updated_at=None,
                data_values=data_values,
                source_freshness_at=freshness,
            )
        )
    return observations


def parse_event_aggregate_rows(payload: dict) -> list[EventAggregateObservation]:
    headers = payload.get("headers")
    rows = payload.get("rows")
    if headers is None or rows is None:
        raise Dhis2ValidationError("Event Analytics aggregate payload missing headers/rows.")
    names = [str(item.get("name")) for item in headers if isinstance(item, dict)]
    try:
        ou_i = names.index("ou")
        pe_i = names.index("pe")
        value_i = names.index("value")
    except ValueError as exc:
        raise Dhis2ValidationError("Event aggregate headers must include ou, pe, value.") from exc
    freshness = parse_optional_datetime(str(payload.get("headerUniq") or "") or None)
    out: list[EventAggregateObservation] = []
    for row in rows:
        if not isinstance(row, list):
            continue
        raw = row[value_i] if value_i < len(row) else None
        try:
            value = float(raw) if raw not in (None, "") else None
        except (TypeError, ValueError):
            value = None
        out.append(
            EventAggregateObservation(
                org_unit_uid=str(row[ou_i]),
                period=str(row[pe_i]),
                metric="event_count",
                value=value,
                source_freshness_at=freshness,
            )
        )
    return out

from __future__ import annotations

import hashlib
import json

from app.integrations.dhis2.errors import Dhis2ValidationError
from app.integrations.dhis2.http import Dhis2HttpClient
from app.integrations.dhis2.types import AggregateObservation, parse_optional_datetime


class AggregateAnalyticsAdapter:
    """Maps DHIS2 Analytics responses to internal observations. No UIDs are hardcoded."""

    def __init__(self, client: Dhis2HttpClient) -> None:
        self.client = client

    def fetch(
        self,
        *,
        dx_uids: list[str],
        org_unit_uids: list[str],
        periods: list[str],
        include_descendants: bool = True,
        extra_params: dict | None = None,
    ) -> list[AggregateObservation]:
        if not dx_uids or not org_unit_uids or not periods:
            return []
        prefix = self.client.settings.dhis2_api_path_prefix.rstrip("/")
        params: dict = {
            "dimension": [
                f"dx:{';'.join(dx_uids)}",
                f"ou:{';'.join(org_unit_uids)}",
                f"pe:{';'.join(periods)}",
            ],
            "skipMeta": "false",
            "paging": "false",
        }
        if include_descendants:
            params["ouMode"] = self.client.settings.dhis2_ou_mode or "DESCENDANTS"
        if extra_params:
            params.update(extra_params)
        payload = self.client.get_json(f"{prefix}/analytics", params=params)
        return parse_analytics_rows(payload)


def parse_analytics_rows(payload: dict) -> list[AggregateObservation]:
    headers = payload.get("headers")
    rows = payload.get("rows")
    if headers is None or rows is None:
        raise Dhis2ValidationError("Analytics payload missing headers/rows.")
    if not isinstance(headers, list) or not isinstance(rows, list):
        raise Dhis2ValidationError("Analytics headers/rows must be lists.")
    names = [str(item.get("name")) for item in headers if isinstance(item, dict)]
    try:
        dx_i = names.index("dx")
        ou_i = names.index("ou")
        pe_i = names.index("pe")
        value_i = names.index("value")
    except ValueError as exc:
        raise Dhis2ValidationError("Analytics headers must include dx, ou, pe, value.") from exc
    coc_i = names.index("co") if "co" in names else None
    freshness = parse_optional_datetime(str(payload.get("serverDate") or "") or None)
    observations: list[AggregateObservation] = []
    for row in rows:
        if not isinstance(row, list) or len(row) <= max(dx_i, ou_i, pe_i, value_i):
            continue
        raw_value = row[value_i]
        checksum = hashlib.sha256(json.dumps(row, default=str).encode("utf-8")).hexdigest()
        value, absence, invalid = parse_numeric_value(raw_value)
        observations.append(
            AggregateObservation(
                org_unit_uid=str(row[ou_i]),
                period=str(row[pe_i]),
                item_uid=str(row[dx_i]),
                value=value,
                category_option_combo_uid=str(row[coc_i]) if coc_i is not None else None,
                source_freshness_at=freshness,
                absence_reason=absence,
                payload_checksum=checksum,
                value_invalid=invalid,
            )
        )
    return observations


def parse_numeric_value(value) -> tuple[float | None, str | None, bool]:
    if value is None or value == "":
        return None, "no_source_row", False
    try:
        return float(value), None, False
    except (TypeError, ValueError):
        return None, "invalid_value", True

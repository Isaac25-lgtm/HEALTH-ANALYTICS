from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field

from app.integrations.dhis2.errors import Dhis2ValidationError
from app.integrations.dhis2.http import Dhis2HttpClient
from app.integrations.dhis2.types import AggregateObservation, parse_optional_datetime

# A single analytics request carries its dimensions in the URL. A national request naming every
# mapped data element and every mapped organisation unit would exceed practical URL and server
# query limits long before it exceeded the response-size cap, so requests are chunked.
DEFAULT_DX_CHUNK = 50
DEFAULT_OU_CHUNK = 100
DATA_ELEMENT_OPERAND = re.compile(
    r"^([A-Za-z][A-Za-z0-9]{10})\.([A-Za-z][A-Za-z0-9]{10})$"
)


@dataclass
class AggregateFetchResult:
    """Observations plus the evidence needed to judge whether the retrieval was complete."""

    observations: list[AggregateObservation] = field(default_factory=list)
    chunks_requested: int = 0
    chunks_succeeded: int = 0

    @property
    def complete(self) -> bool:
        return self.chunks_requested > 0 and self.chunks_succeeded == self.chunks_requested


def _chunk(values: list[str], size: int) -> list[list[str]]:
    if size < 1:
        raise ValueError("Chunk size must be positive.")
    return [values[index : index + size] for index in range(0, len(values), size)]


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
        include_descendants: bool = False,
        include_category_option_combos: bool = False,
        dx_chunk_size: int = DEFAULT_DX_CHUNK,
        ou_chunk_size: int = DEFAULT_OU_CHUNK,
        extra_params: dict | None = None,
    ) -> AggregateFetchResult:
        """Retrieve observations in bounded chunks, merged deterministically.

        Every chunk must succeed. An exception from any one of them propagates, so a job can never
        be marked fully successful on a partial retrieval.
        """
        result = AggregateFetchResult()
        if not dx_uids or not org_unit_uids or not periods:
            return result
        prefix = self.client.settings.dhis2_api_path_prefix.rstrip("/")
        seen: set[tuple[str, str, str, str]] = set()
        for dx_group in _chunk(list(dict.fromkeys(dx_uids)), dx_chunk_size):
            for ou_group in _chunk(list(dict.fromkeys(org_unit_uids)), ou_chunk_size):
                result.chunks_requested += 1
                dimensions = [
                    f"dx:{';'.join(dx_group)}",
                    f"ou:{';'.join(ou_group)}",
                    f"pe:{';'.join(periods)}",
                ]
                if include_category_option_combos:
                    # The response only carries a `co` column when the dimension is requested.
                    # Without this, category detail silently collapsed into the element total.
                    dimensions.append("co")
                params: dict = {
                    "dimension": dimensions,
                    "skipMeta": "false",
                    "paging": "false",
                }
                # The service layer supplies a complete, non-overlapping peer cohort. Expanding
                # every member again would return child rows and could mix aggregation levels.
                # Keep this compatibility argument, but never allow it to weaken explicit scope.
                params["ouMode"] = "SELECTED"
                if extra_params:
                    params.update(extra_params)
                payload = self.client.get_json(f"{prefix}/analytics", params=params)
                for observation in parse_analytics_rows(payload):
                    identity = (
                        observation.item_uid,
                        observation.org_unit_uid,
                        observation.period,
                        observation.category_option_combo_uid or "",
                    )
                    if identity in seen:
                        continue
                    seen.add(identity)
                    result.observations.append(observation)
                result.chunks_succeeded += 1
        return result


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
        raw_dx = str(row[dx_i])
        item_uid = raw_dx
        category_option_combo_uid = str(row[coc_i]) if coc_i is not None else None
        operand = DATA_ELEMENT_OPERAND.fullmatch(raw_dx)
        if operand:
            item_uid, operand_coc = operand.groups()
            if category_option_combo_uid and category_option_combo_uid != operand_coc:
                raise Dhis2ValidationError(
                    "Analytics row category option combo conflicts with its data element operand."
                )
            category_option_combo_uid = operand_coc
        checksum = hashlib.sha256(json.dumps(row, default=str).encode("utf-8")).hexdigest()
        value, absence, invalid = parse_numeric_value(raw_value)
        observations.append(
            AggregateObservation(
                org_unit_uid=str(row[ou_i]),
                period=str(row[pe_i]),
                item_uid=item_uid,
                value=value,
                category_option_combo_uid=category_option_combo_uid,
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

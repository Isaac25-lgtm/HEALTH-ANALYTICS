"""MPDSR event minimisation.

HPIP stores the smallest set of MPDSR facts its calculations need, and nothing else. This is a
whitelist with a strict format per field: a semantic field is stored only when it appears in
``APPROVED_EVENT_SEMANTIC_FIELDS`` *and* its value has the exact shape that field allows.

- ``event_type`` is a short snake_case code;
- ``death_date``, ``notification_date`` and ``review_date`` are calendar dates, stored as
  ``YYYY-MM-DD`` (a time of day is discarded);
- ``structured_cause_mentions`` is a short list of codes from the approved cause taxonomy, and
  is dropped entirely while no taxonomy is approved.

Anything else — a name, a phone number, a location, a narrative, a nested object, a number, or
an approved key holding any of those — is dropped at ingestion, never truncated or filtered
later. There is no free-text cause field. Event UIDs are held only in
``raw_event_snapshots.event_uid`` and expire with the 24-hour event cache.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from app.domain.mpdsr_cause_taxonomy import CauseTaxonomy, current_cause_taxonomy

# Every field the calculation engine actually consumes. Adding to this set is a governance
# decision: it widens what HPIP stores about a death.
APPROVED_EVENT_SEMANTIC_FIELDS = frozenset(
    {
        "event_type",
        "death_date",
        "notification_date",
        "review_date",
        "structured_cause_mentions",
    }
)
DATE_FIELDS = frozenset({"death_date", "notification_date", "review_date"})
CAUSE_FIELD = "structured_cause_mentions"

MAX_LIST_ITEMS = 12
EVENT_TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,39}$")
# A date, optionally followed by a DHIS2 time component that is discarded.
DATE_PATTERN = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:[T ][0-9:.]{2,15}(?:Z|[+-]\d{2}:?\d{2})?)?$")

DROP_NOT_APPROVED = "not_approved_field"
DROP_NESTED = "nested_payload"
DROP_INVALID_FORMAT = "invalid_format"
DROP_UNSUPPORTED_TYPE = "unsupported_type"
DROP_TOO_MANY_ITEMS = "too_many_items"
DROP_NO_TAXONOMY = "cause_taxonomy_not_configured"
DROP_NOT_IN_TAXONOMY = "cause_code_not_in_taxonomy"


@dataclass
class MinimisationResult:
    values: dict
    dropped: dict[str, str] = field(default_factory=dict)

    @property
    def dropped_count(self) -> int:
        return len(self.dropped)


def _shape_problem(value) -> str | None:
    if isinstance(value, dict):
        return DROP_NESTED
    if isinstance(value, list | tuple | set | bytes | bytearray):
        return DROP_UNSUPPORTED_TYPE
    if not isinstance(value, str):
        return DROP_UNSUPPORTED_TYPE
    return None


def normalise_event_date(value) -> str | None:
    """``YYYY-MM-DD`` for a valid calendar date string, else None."""
    if not isinstance(value, str):
        return None
    match = DATE_PATTERN.fullmatch(value.strip())
    if match is None:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3))).isoformat()
    except ValueError:
        return None


def _causes(value, taxonomy: CauseTaxonomy | None) -> tuple[list[str], str | None]:
    if taxonomy is None:
        return [], DROP_NO_TAXONOMY
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list | tuple):
        return [], DROP_NESTED if isinstance(value, dict) else DROP_UNSUPPORTED_TYPE
    if len(value) > MAX_LIST_ITEMS:
        return [], DROP_TOO_MANY_ITEMS
    kept: list[str] = []
    reason = None
    for item in value:
        if taxonomy.contains(item):
            if item not in kept:
                kept.append(item)
        else:
            reason = _shape_problem(item) or DROP_NOT_IN_TAXONOMY
    return kept, reason


def minimise_event_values(mapped: dict | None, *, taxonomy: CauseTaxonomy | None = None) -> MinimisationResult:
    """Keep only approved, correctly shaped, non-identifying facts from a mapped event payload.

    ``taxonomy`` defaults to the approved cause taxonomy, which is currently not configured.
    """
    active_taxonomy = taxonomy if taxonomy is not None else current_cause_taxonomy()
    result = MinimisationResult(values={})
    for key, value in (mapped or {}).items():
        name = str(key)
        if name not in APPROVED_EVENT_SEMANTIC_FIELDS:
            result.dropped[name] = DROP_NOT_APPROVED
            continue
        if name == CAUSE_FIELD:
            kept, reason = _causes(value, active_taxonomy)
            if kept:
                result.values[name] = kept
            if reason:
                result.dropped[name] = reason
            continue
        problem = _shape_problem(value)
        if problem:
            result.dropped[name] = problem
            continue
        if name in DATE_FIELDS:
            normalised = normalise_event_date(value)
            if normalised is None:
                result.dropped[name] = DROP_INVALID_FORMAT
            else:
                result.values[name] = normalised
            continue
        if name == "event_type":
            if EVENT_TYPE_PATTERN.fullmatch(value):
                result.values[name] = value
            else:
                result.dropped[name] = DROP_INVALID_FORMAT
    return result

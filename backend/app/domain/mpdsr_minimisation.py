"""MPDSR event minimisation.

HPIP stores the smallest set of MPDSR facts its calculations need, and nothing else. This is a
whitelist: a semantic field is stored only when it appears in ``APPROVED_EVENT_SEMANTIC_FIELDS``.
Anything a mapping labels differently — a name, an identifier, a narrative, a phone number, an
arbitrary DHIS2 attribute — is dropped at ingestion, not filtered later.

Nested structures are never stored: an approved field may only hold a short scalar or a short
list of scalars, so an identifying payload cannot travel inside an approved key.

Event UIDs are held only in ``raw_event_snapshots.event_uid`` for deduplication and
reconciliation, and expire with the 24-hour event cache (MPDSR_EVENT_RETENTION_HOURS).
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Every field the calculation engine actually consumes. Adding to this set is a governance
# decision: it widens what HPIP stores about a death.
APPROVED_EVENT_SEMANTIC_FIELDS = frozenset(
    {
        "event_type",
        "death_date",
        "notification_date",
        "review_date",
        # Structured cause categories only. Cause analysis itself stays disabled until an
        # owner-approved taxonomy and minimum cell count exist.
        "cause_mentions",
        "structured_cause_mentions",
    }
)

# A category code or ISO date, never a sentence. Longer values are dropped, not truncated.
MAX_VALUE_LENGTH = 120
MAX_LIST_ITEMS = 12

DROP_NOT_APPROVED = "not_approved_field"
DROP_NESTED = "nested_payload"
DROP_TOO_LONG = "value_too_long"
DROP_UNSUPPORTED_TYPE = "unsupported_type"


@dataclass
class MinimisationResult:
    values: dict
    dropped: dict[str, str] = field(default_factory=dict)

    @property
    def dropped_count(self) -> int:
        return len(self.dropped)


def _scalar(value) -> tuple[bool, str | None]:
    if value is None or isinstance(value, bool | int | float):
        return True, None
    if isinstance(value, str):
        if len(value) > MAX_VALUE_LENGTH:
            return False, DROP_TOO_LONG
        return True, None
    if isinstance(value, dict | list | tuple | set | bytes | bytearray):
        return False, DROP_NESTED if isinstance(value, dict) else DROP_UNSUPPORTED_TYPE
    return False, DROP_UNSUPPORTED_TYPE


def minimise_event_values(mapped: dict | None) -> MinimisationResult:
    """Keep only approved, non-identifying scalar facts from an already-mapped event payload."""
    result = MinimisationResult(values={})
    for key, value in (mapped or {}).items():
        name = str(key)
        if name not in APPROVED_EVENT_SEMANTIC_FIELDS:
            result.dropped[name] = DROP_NOT_APPROVED
            continue
        if isinstance(value, list | tuple):
            kept = []
            reason = None
            for item in list(value)[:MAX_LIST_ITEMS]:
                ok, item_reason = _scalar(item)
                if ok and item is not None:
                    kept.append(item)
                else:
                    reason = item_reason or DROP_UNSUPPORTED_TYPE
            if kept:
                result.values[name] = kept
            if reason:
                result.dropped[name] = reason
            continue
        ok, reason = _scalar(value)
        if ok:
            result.values[name] = value
        else:
            result.dropped[name] = reason or DROP_UNSUPPORTED_TYPE
    return result

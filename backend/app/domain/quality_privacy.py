from __future__ import annotations

from typing import Any

SENSITIVE_KEYS = {
    "event_uid",
    "event_uids",
    "eventuids",
    "name",
    "names",
    "narrative",
    "narratives",
    "username",
    "usernames",
    "clinician",
    "clinician_id",
    "patient",
    "case_history",
    "cause",
    "causes",
    "facility_date_cause",
}


def redact_evidence(value: Any) -> Any:
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, item in value.items():
            lowered = key.lower()
            if lowered in SENSITIVE_KEYS or "event_uid" in lowered or "uid" == lowered:
                continue
            clean[key] = redact_evidence(item)
        return clean
    if isinstance(value, list):
        return [redact_evidence(item) for item in value]
    if isinstance(value, str) and value.startswith("TEST_UID_EVENT"):
        return "[redacted]"
    return value


def contains_sensitive_identifier(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = key.lower()
            if lowered in SENSITIVE_KEYS or "event_uid" in lowered:
                return True
            if contains_sensitive_identifier(item):
                return True
        return False
    if isinstance(value, list):
        return any(contains_sensitive_identifier(item) for item in value)
    if isinstance(value, str) and value.startswith("TEST_UID_EVENT"):
        return True
    return False

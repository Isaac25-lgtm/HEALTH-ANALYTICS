from __future__ import annotations

import logging
import re
from typing import Any

_SECRET_KEYS = {
    "password",
    "authorization",
    "token",
    "access_token",
    "api_key",
    "secret",
    "dhis2_password",
    "pat",
}
_SENSITIVE_FIELD_RE = re.compile(
    r"(patient|name|narrative|username|clinician|next_of_kin|address|phone)",
    re.IGNORECASE,
)


def redact_mapping(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not payload:
        return {}
    clean: dict[str, Any] = {}
    for key, value in payload.items():
        lowered = key.lower()
        if lowered in _SECRET_KEYS or _SENSITIVE_FIELD_RE.search(key):
            clean[key] = "[redacted]"
        elif isinstance(value, dict):
            clean[key] = redact_mapping(value)
        else:
            clean[key] = value
    return clean


def safe_url(url: str) -> str:
    return re.sub(r"(://[^:/]+:)[^@/]+@", r"\1***@", url)


class RedactingLogger:
    def __init__(self, name: str = "hpip.dhis2") -> None:
        self._log = logging.getLogger(name)

    def info(self, message: str, **fields: Any) -> None:
        self._log.info("%s %s", message, redact_mapping(fields))

    def warning(self, message: str, **fields: Any) -> None:
        self._log.warning("%s %s", message, redact_mapping(fields))

    def error(self, message: str, **fields: Any) -> None:
        self._log.error("%s %s", message, redact_mapping(fields))

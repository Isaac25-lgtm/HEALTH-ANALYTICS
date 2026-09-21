from __future__ import annotations

from collections import deque
from typing import Any

from sqlalchemy.orm import Session

from app.integrations.dhis2.redaction import redact_mapping

# A diagnostic convenience only; durable events belong in ``operational_events``. Keeping this
# bounded prevents a long-running API or worker from accumulating one object per request forever.
_BUFFER_LIMIT = 500
_BUFFER: deque[dict[str, Any]] = deque(maxlen=_BUFFER_LIMIT)


def record_operational_event(
    event_type: str,
    *,
    duration_ms: int | None = None,
    retry_count: int | None = None,
    records_received: int | None = None,
    records_stored: int | None = None,
    records_rejected: int | None = None,
    job_id: str | None = None,
    payload: dict | None = None,
    session: Session | None = None,
) -> dict:
    event = {
        "event_type": event_type,
        "duration_ms": duration_ms,
        "retry_count": retry_count,
        "records_received": records_received,
        "records_stored": records_stored,
        "records_rejected": records_rejected,
        "job_id": job_id,
        "payload": redact_mapping(payload),
    }
    _BUFFER.append(event)
    if session is not None:
        from app.models import OperationalEvent

        session.add(
            OperationalEvent(
                event_type=event_type,
                duration_ms=duration_ms,
                retry_count=retry_count,
                records_received=records_received,
                records_stored=records_stored,
                records_rejected=records_rejected,
                job_id=job_id,
                payload=redact_mapping(payload),
            )
        )
    return event


def recent_operational_events() -> list[dict[str, Any]]:
    return list(_BUFFER)


def clear_operational_events() -> None:
    _BUFFER.clear()

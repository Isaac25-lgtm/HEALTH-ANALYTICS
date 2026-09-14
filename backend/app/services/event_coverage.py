"""MPDSR event-cohort coverage: when may an empty cohort be reported as zero?

A zero is only a verified zero when a successful, complete, appropriately scoped
Tracker synchronisation proves the cohort. Anything else (no sync, partial or
truncated sync, a window that does not reach far enough, stale extraction, or an
unavailable event mapping) leaves the count unknown. Unknown is never zero.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain.enums import ConnectorType, EventCoverageStatus, JobStatus, ProgrammeCode, UnavailableReason
from app.domain.periods import parse_period
from app.models import OrgUnit, Programme, SyncJob
from app.services.geography import ancestors
from app.services.mappings import MappingSelectionError, resolve_programme_uid

CACHE_KEY = "event_coverage_cache"


def _as_aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _result(status: EventCoverageStatus, reason_code: str | None, reason: str, **extra) -> dict:
    return {"status": status.value, "reason_code": reason_code, "reason": reason, **extra}


def evaluate_event_coverage(
    session: Session,
    *,
    org_unit: OrgUnit,
    period: str,
    required_end: date | None,
    now: datetime | None = None,
) -> dict:
    """Return verified coverage for the MPDSR death cohort of ``period`` at ``org_unit``.

    ``required_end`` is the last event date the source window must include. ``None``
    means the window must reach the extraction date itself (completion counts can
    change until the moment of extraction).
    """
    batch = session.info.get("calc_batch")
    cache_key = (org_unit.id, period, required_end)
    if batch is not None:
        cached = batch.setdefault(CACHE_KEY, {}).get(cache_key)
        if cached is not None:
            return cached
    result = _evaluate(session, org_unit=org_unit, period=period, required_end=required_end, now=now)
    if batch is not None:
        batch.setdefault(CACHE_KEY, {})[cache_key] = result
    return result


def _evaluate(
    session: Session,
    *,
    org_unit: OrgUnit,
    period: str,
    required_end: date | None,
    now: datetime | None,
) -> dict:
    cohort = parse_period(period)
    moment = _as_aware(now or datetime.now(UTC))
    stale_after = timedelta(hours=get_settings().dhis2_stale_hours)
    requirement = {
        "cohort_start": cohort.start.isoformat(),
        "cohort_end": cohort.end.isoformat(),
        "required_window_end": required_end.isoformat() if required_end else "extraction_date",
    }
    programme = session.scalar(select(Programme).where(Programme.code == ProgrammeCode.MPDSR.value))
    if programme is None:
        return _result(
            EventCoverageStatus.UNVERIFIED,
            UnavailableReason.EVENT_COVERAGE_UNVERIFIED.value,
            "the MPDSR programme is not configured.",
            requirement=requirement,
        )
    scope_ids = {org_unit.id, *(unit.id for unit in ancestors(session, org_unit, include_inactive=True))}
    jobs = session.scalars(
        select(SyncJob)
        .where(
            SyncJob.job_type == ConnectorType.TRACKER.value,
            SyncJob.programme_id == programme.id,
            SyncJob.org_unit_id.in_(scope_ids),
        )
        .order_by(SyncJob.finished_at.desc().nulls_last(), SyncJob.created_at.desc().nulls_last())
    ).all()
    if not jobs:
        return _result(
            EventCoverageStatus.UNVERIFIED,
            UnavailableReason.EVENT_COVERAGE_UNVERIFIED.value,
            "no MPDSR Tracker synchronisation covers this geography.",
            requirement=requirement,
        )
    failures: list[str] = []
    for job in jobs:
        if job.status != JobStatus.SUCCEEDED.value or job.cancelled or job.finished_at is None:
            failures.append("incomplete")
            continue
        if job.page_limit_reached or (job.rejected_count or 0) > 0:
            failures.append("incomplete")
            continue
        if job.window_start is None or job.window_end is None:
            failures.append("window")
            continue
        finished = _as_aware(job.finished_at)
        needed_end = required_end or finished.date()
        if job.window_start > cohort.start or job.window_end < needed_end:
            failures.append("window")
            continue
        if moment - finished > stale_after:
            failures.append("stale")
            continue
        try:
            program_uid = resolve_programme_uid(
                session, programme.id, job.mapping_version or "v1", as_of=cohort.end
            )
        except MappingSelectionError:
            program_uid = None
        if not program_uid:
            failures.append("mapping")
            continue
        return _result(
            EventCoverageStatus.VERIFIED,
            None,
            "a successful, complete and current MPDSR Tracker synchronisation covers this cohort.",
            requirement=requirement,
            sync_job_id=str(job.id),
            window_start=job.window_start.isoformat(),
            window_end=job.window_end.isoformat(),
            finished_at=finished.isoformat(),
            mapping_version=job.mapping_version,
        )
    messages = {
        "incomplete": (
            "the only MPDSR synchronisations for this geography were partial, truncated, cancelled or failed."
        ),
        "window": "no successful MPDSR synchronisation window spans the cohort and its required follow-up period.",
        "stale": "the covering MPDSR synchronisation is older than the configured freshness window.",
        "mapping": "the MPDSR event mapping is unavailable or ambiguous for this cohort.",
    }
    for key in ("mapping", "stale", "window", "incomplete"):
        if key in failures:
            return _result(
                EventCoverageStatus.UNVERIFIED,
                UnavailableReason.EVENT_COVERAGE_UNVERIFIED.value,
                messages[key],
                requirement=requirement,
                coverage_failure=key,
            )
    return _result(
        EventCoverageStatus.UNVERIFIED,
        UnavailableReason.EVENT_COVERAGE_UNVERIFIED.value,
        "MPDSR synchronisation coverage could not be verified.",
        requirement=requirement,
    )

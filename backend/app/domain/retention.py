"""Retention policy definitions and cutoff arithmetic.

HPIP keeps routine DHIS2 data only as a short-lived cache; the calculated results, their
provenance and the audit trail are what is retained. Month-based windows use real calendar
months, never a fixed-day approximation, so a 36-month policy means 36 calendar months.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

RAW_AGGREGATES = "raw_aggregates"
MPDSR_EVENTS = "mpdsr_events"
EXPORT_FILES = "export_files"
EXPORT_JOBS = "export_jobs"
SNAPSHOTS = "calculation_snapshots"
AUDIT_LOGS = "audit_logs"

POLICY_ORDER = (RAW_AGGREGATES, MPDSR_EVENTS, EXPORT_FILES, EXPORT_JOBS, SNAPSHOTS, AUDIT_LOGS)


def utc_now() -> datetime:
    return datetime.now(UTC)


def subtract_months(moment: datetime, months: int) -> datetime:
    """Calendar-aware month subtraction, clamping to the last valid day of the target month."""
    if months < 0:
        raise ValueError("months must not be negative")
    total = (moment.year * 12 + (moment.month - 1)) - months
    year, month = divmod(total, 12)
    month += 1
    day = min(moment.day, calendar.monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)


@dataclass(frozen=True)
class RetentionPolicy:
    """One retention rule: what expires, when, and which timestamp decides."""

    name: str
    entity: str
    description: str
    basis: str
    window: str

    def cutoff(self, settings, now: datetime | None = None) -> datetime:
        moment = (now or utc_now()).astimezone(UTC)
        if self.name == RAW_AGGREGATES:
            return moment - timedelta(days=settings.raw_aggregate_retention_days)
        if self.name == MPDSR_EVENTS:
            return moment - timedelta(hours=settings.mpdsr_event_retention_hours)
        if self.name == EXPORT_FILES:
            return moment - timedelta(hours=settings.export_file_retention_hours)
        if self.name == EXPORT_JOBS:
            return moment - timedelta(days=settings.export_job_retention_days)
        if self.name == SNAPSHOTS:
            return subtract_months(moment, settings.calculation_snapshot_retention_months)
        if self.name == AUDIT_LOGS:
            return subtract_months(moment, settings.audit_log_retention_months)
        raise ValueError(f"Unknown retention policy: {self.name}")


POLICIES: dict[str, RetentionPolicy] = {
    RAW_AGGREGATES: RetentionPolicy(
        name=RAW_AGGREGATES,
        entity="raw_aggregate_values",
        description="Routine DHIS2 aggregate cache. DHIS2 remains the authoritative source.",
        basis="extracted_at",
        window="RAW_AGGREGATE_RETENTION_DAYS",
    ),
    MPDSR_EVENTS: RetentionPolicy(
        name=MPDSR_EVENTS,
        entity="raw_event_snapshots",
        description="Minimised MPDSR event cache, including temporary event UIDs.",
        basis="extracted_at",
        window="MPDSR_EVENT_RETENTION_HOURS",
    ),
    EXPORT_FILES: RetentionPolicy(
        name=EXPORT_FILES,
        entity="export_artifacts",
        description="Generated export files. Job metadata and checksums outlive the bytes.",
        basis="artifact_expires_at (set at publication)",
        window="EXPORT_FILE_RETENTION_HOURS",
    ),
    EXPORT_JOBS: RetentionPolicy(
        name=EXPORT_JOBS,
        entity="export_jobs",
        description="Terminal export job metadata. Active and queued jobs are never purged by age.",
        basis="finished_at of a terminal job",
        window="EXPORT_JOB_RETENTION_DAYS",
    ),
    SNAPSHOTS: RetentionPolicy(
        name=SNAPSHOTS,
        entity="analysis_snapshots",
        description="Analysis snapshots with their calculation runs, values and evidence.",
        basis="created_at",
        window="CALCULATION_SNAPSHOT_RETENTION_MONTHS",
    ),
    AUDIT_LOGS: RetentionPolicy(
        name=AUDIT_LOGS,
        entity="audit_log",
        description="Audit trail of user and system actions.",
        basis="created_at",
        window="AUDIT_LOG_RETENTION_MONTHS",
    ),
}


def retention_cutoffs(settings, now: datetime | None = None) -> dict[str, datetime]:
    moment = now or utc_now()
    return {name: policy.cutoff(settings, moment) for name, policy in POLICIES.items()}


def policy_summary(settings) -> list[dict]:
    """Operator-facing description of the active policies. Contains no data values."""
    cutoffs = retention_cutoffs(settings)
    return [
        {
            "policy": policy.name,
            "entity": policy.entity,
            "basis": policy.basis,
            "window_setting": policy.window,
            "cutoff_utc": cutoffs[policy.name].isoformat(),
            "description": policy.description,
        }
        for policy in (POLICIES[name] for name in POLICY_ORDER)
    ]

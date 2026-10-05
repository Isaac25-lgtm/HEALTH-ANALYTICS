"""On-demand facility figures for a district (owner decision D-068).

District, regional and national figures come from the stored district-month data. Facility
figures are fetched from DHIS2 only when someone opens a district: the months of the requested
period that are not yet stored are extracted for that district's mapped facilities, as one
ordinary audited sync job, in the background. The user's home district is prefetched at sign-in.

Months are the single stored source. A closed month is fetched once; the two most recent closed
months are re-checked after ``RECENT_REFRESH_HOURS`` because facilities keep reporting late.
Nothing is shown as zero while loading, and a failed load is reported, never hidden.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain.enums import JobStatus, OrgUnitLevel
from app.domain.modules import MODULE_PROGRAMME
from app.domain.periods import parse_period
from app.integrations.dhis2.gates import Dhis2Disabled, ensure_extraction_enabled
from app.integrations.dhis2.periods import months_in
from app.models import OrgUnit, Programme, RawAggregateValue, SourceMapping, SyncJob, User
from app.services.geography import descendants
from app.services.sync import FACILITY_AGGREGATE_JOB_TYPE as FACILITY_JOB_TYPE
from app.services.sync import enqueue_sync_job

RECENT_REFRESH_HOURS = 24
HISTORY_START = "202007"
ACTIVE_STATES = (JobStatus.QUEUED.value, JobStatus.RUNNING.value)
DISTRICT_LEVELS = {OrgUnitLevel.DISTRICT.value, OrgUnitLevel.CITY.value}
logger = logging.getLogger(__name__)


@dataclass
class FacilityDataStatus:
    status: str  # ready | loading | failed | unavailable | not_applicable
    job_id: str | None = None
    months_requested: int = 0
    months_loaded: int = 0
    message: str | None = None
    start_job: bool = False
    missing: list[str] = field(default_factory=list)
    district_id: UUID | None = None
    programme_id: UUID | None = None
    mapping_version: str | None = None

    def payload(self) -> dict:
        return {
            "status": self.status,
            "job_id": self.job_id,
            "months_requested": self.months_requested,
            "months_loaded": self.months_loaded,
            "message": self.message,
        }


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _last_closed_month(today: date) -> str:
    year, month = today.year, today.month - 1
    if month == 0:
        year, month = year - 1, 12
    return f"{year}{month:02d}"


def _month_keys(start: str, end: str) -> list[str]:
    year, month = int(start[:4]), int(start[4:])
    months = []
    while f"{year}{month:02d}" <= end:
        months.append(f"{year}{month:02d}")
        month += 1
        if month > 12:
            month, year = 1, year + 1
    return months


def _district_for(session: Session, org_unit: OrgUnit) -> OrgUnit | None:
    unit: OrgUnit | None = org_unit
    while unit is not None and unit.level_type not in DISTRICT_LEVELS:
        unit = session.get(OrgUnit, unit.parent_id) if unit.parent_id else None
    return unit


def _jobs(session: Session, target: OrgUnit, programme: Programme) -> list[SyncJob]:
    return list(
        session.scalars(
            select(SyncJob)
            .where(
                SyncJob.job_type == FACILITY_JOB_TYPE,
                SyncJob.org_unit_id == target.id,
                SyncJob.programme_id == programme.id,
            )
            .order_by(SyncJob.created_at.desc())
        ).all()
    )


def _covered(job: SyncJob) -> set[str]:
    if not job.period_from or not job.period_to:
        return set()
    return set(_month_keys(job.period_from, job.period_to))


def facility_data_status(
    session: Session,
    *,
    org_unit: OrgUnit,
    period: str,
    module: str,
    now: datetime | None = None,
) -> FacilityDataStatus:
    """What is stored for this district and period, and whether a load is needed."""
    district = _district_for(session, org_unit)
    if district is None:
        return FacilityDataStatus("not_applicable")
    programme = session.scalar(select(Programme).where(Programme.code == MODULE_PROGRAMME[module]))
    if programme is None:
        return FacilityDataStatus("unavailable", message="The programme is not configured.")
    effective = parse_period(period).start
    mappings = list(
        session.scalars(
            select(SourceMapping).where(
                SourceMapping.programme_id == programme.id,
                SourceMapping.enabled.is_(True),
                or_(SourceMapping.valid_from.is_(None), SourceMapping.valid_from <= effective),
                or_(SourceMapping.valid_to.is_(None), SourceMapping.valid_to >= effective),
            )
        ).all()
    )
    versions = {mapping.mapping_version for mapping in mappings}
    if len(versions) != 1:
        return FacilityDataStatus("unavailable", message="A single approved in-force mapping version is required.")
    mapping_version = next(iter(versions))
    now = now or datetime.now(UTC)
    last_closed = _last_closed_month(now.date())
    wanted = [month for month in months_in(parse_period(period)) if HISTORY_START <= month <= last_closed]
    if not wanted:
        return FacilityDataStatus("ready", message="No closed month in this period yet.")
    previous = _last_closed_month(parse_period(last_closed).start)
    recent = {previous, last_closed}
    jobs = _jobs(session, org_unit, programme)
    active = next((job for job in jobs if job.status in ACTIVE_STATES and _covered(job) & set(wanted)), None)
    loaded: set[str] = set()
    expected_facilities = {
        str(unit.id)
        for unit in descendants(session, org_unit, include_self=True, period=period)
        if unit.level_type == OrgUnitLevel.FACILITY.value
    }
    for job in jobs:
        manifest = job.coverage_manifest or {}
        if (
            job.status != JobStatus.SUCCEEDED.value
            or job.mapping_version != mapping_version
            or not manifest.get("complete")
            or job.cancelled
            or job.page_limit_reached
            or job.rejected_count
            or not expected_facilities <= set(manifest.get("org_unit_ids", []))
            or not {str(mapping.id) for mapping in mappings} <= set(manifest.get("mapping_ids", []))
        ):
            continue
        if (
            job.stored_count
            and session.scalar(select(func.count(RawAggregateValue.id)).where(RawAggregateValue.sync_job_id == job.id))
            < job.stored_count
        ):
            # A retained successful-job manifest must not pretend that purged raw figures
            # are still available. A zero-row complete extraction needs no raw row.
            continue
        finished = _aware(job.finished_at)
        fresh = finished is not None and now - finished < timedelta(hours=RECENT_REFRESH_HOURS)
        for month in manifest.get("periods", []):
            if month not in recent or fresh:
                loaded.add(month)
    missing = [month for month in wanted if month not in loaded]
    status = FacilityDataStatus("ready", months_requested=len(wanted), months_loaded=len(wanted) - len(missing))
    if not missing:
        return status
    if active is not None:
        status.status = "loading"
        status.job_id = str(active.id)
        status.message = "Loading facility data from DHIS2."
        return status
    latest = jobs[0] if jobs else None
    if (
        latest is not None
        and latest.status == JobStatus.FAILED.value
        and latest.error_code in {"sync_enqueue_failed", "facility_load_failed"}
        and _covered(latest) >= set(missing)
    ):
        status.status = "loading"
        status.job_id = str(latest.id)
        status.message = "Waiting for durable worker-queue recovery. Missing facility figures are not zero."
        return status
    if latest is not None and latest.status == JobStatus.FAILED.value and _covered(latest) >= set(missing):
        finished = _aware(latest.finished_at)
        if finished is not None and now - finished < timedelta(minutes=10):
            status.status = "failed"
            status.job_id = str(latest.id)
            status.message = "Facility data could not be loaded from DHIS2. Try again shortly."
            return status
    status.status = "loading"
    status.message = "Loading facility data from DHIS2."
    status.start_job = True
    status.missing = missing
    status.district_id = district.id
    status.programme_id = programme.id
    status.mapping_version = mapping_version
    return status


def queue_facility_load(
    session: Session, *, user: User | None, org_unit: OrgUnit, period: str, module: str
) -> FacilityDataStatus:
    """Create the load job when one is needed; the caller runs it after committing."""
    if user is not None:
        from app.domain.enums import ActionPermission
        from app.services.authorization import require_action, require_org_unit_access, require_programme_access

        require_action(session, user, ActionPermission.VIEW)
        require_org_unit_access(session, user, org_unit.id, period=period)
        require_programme_access(session, user, MODULE_PROGRAMME[module])
    status = facility_data_status(session, org_unit=org_unit, period=period, module=module)
    if not status.start_job:
        return status
    try:
        ensure_extraction_enabled(get_settings())
    except Dhis2Disabled:
        # No DHIS2 connection in this environment: show what is stored and never pretend to load.
        return FacilityDataStatus(
            "unavailable",
            months_requested=status.months_requested,
            months_loaded=status.months_loaded,
            message="Facility data cannot be loaded here because DHIS2 extraction is switched off.",
        )
    missing = status.missing
    # The requested authorised subtree is the extraction target, not its wider district.
    identity = f"{org_unit.id}|{status.programme_id}|{status.mapping_version}|{missing[0]}|{missing[-1]}"
    key = "facility:" + hashlib.sha256(identity.encode()).hexdigest()
    if session.get_bind().dialect.name == "postgresql":
        lock_key = int.from_bytes(hashlib.sha256(identity.encode()).digest()[:8], "big", signed=True)
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})
    query = select(SyncJob).where(SyncJob.idempotency_key == key, SyncJob.status.in_(ACTIVE_STATES))
    job = session.scalar(query)
    if job is None:
        try:
            with session.begin_nested():
                job = enqueue_sync_job(
                    session,
                    org_unit=org_unit,
                    periods=[missing[0], missing[-1]],
                    user=user,
                    job_type=FACILITY_JOB_TYPE,
                    programme_id=status.programme_id,
                    mapping_version=status.mapping_version,
                )
                job.idempotency_key = key
                session.flush()
        except IntegrityError:
            job = session.scalar(query)
            if job is None:
                raise
            status.start_job = False
    else:
        status.start_job = False
    job.period_from, job.period_to = missing[0], missing[-1]
    job.notes = "D-068 authorised-subtree on-demand facility load"
    status.job_id = str(job.id)
    return status


def run_facility_job(job_id: str | UUID) -> None:
    """Dispatch the durable sync task after commit; never run a long HTTP job in ASGI."""
    from app.db.session import get_session_factory
    from app.services.sync import dispatch_sync_job, should_run_eager
    from app.workers.tasks import run_execute_sync_job

    if should_run_eager():
        run_execute_sync_job(str(job_id))
        return

    session = get_session_factory()()
    try:
        dispatch_sync_job(UUID(str(job_id)))
    except Exception:  # noqa: BLE001 - a background load must record failure, not crash the worker
        session.rollback()
        logger.warning("facility_load_failed")
        session.execute(
            update(SyncJob)
            .where(
                SyncJob.id == UUID(str(job_id)), SyncJob.status == JobStatus.QUEUED.value, SyncJob.cancelled.is_(False)
            )
            .values(
                status=JobStatus.FAILED.value,
                error_code="facility_load_failed",
                error_message="Worker publication failed; durable dispatch recovery will retry.",
                finished_at=datetime.now(UTC),
            )
        )
        session.commit()
    finally:
        session.close()


# One representative module per programme: a facility load fetches the whole programme.
PREFETCH_MODULES = {"MNCH": "anc", "EPI": "immunization", "MPDSR": "mpdsr"}


def _latest_closed_financial_year(today: date) -> str:
    start = today.year if today.month >= 7 else today.year - 1
    closed = start - 1
    return f"FY{closed}/{str(closed + 1)[2:]}"


def prefetch_home_district(session: Session, user: User) -> list[str]:
    """Queue loads for a district-scoped user's home district at sign-in (D-068).

    National and regional users need nothing: their figures are already stored. Returns the job
    IDs to run after the caller commits; never raises, so sign-in cannot fail because of it.
    """
    from app.services.authorization import primary_landing_org_unit, programme_scope_codes

    try:
        landing = primary_landing_org_unit(session, user)
        if landing is None or _district_for(session, landing) is None:
            return []
        programmes = programme_scope_codes(session, user)
        period = _latest_closed_financial_year(datetime.now(UTC).date())
        jobs = []
        for code, module in PREFETCH_MODULES.items():
            if code not in programmes:
                continue
            try:
                with session.begin_nested():
                    status = queue_facility_load(session, user=user, org_unit=landing, period=period, module=module)
                if status.start_job and status.job_id:
                    jobs.append(status.job_id)
            except Exception:  # noqa: BLE001 - isolate this programme, preserve earlier dispatch IDs
                logger.warning("facility_programme_prefetch_failed")
        return jobs
    except Exception:  # noqa: BLE001 - prefetch is best effort and must never block sign-in
        logger.warning("facility_prefetch_failed")
        return []

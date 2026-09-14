from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain.enums import AbsenceReason, ConnectorType, JobStatus, MappingSourceSystem
from app.domain.periods import PeriodError, parse_period
from app.integrations.dhis2.aggregate import AggregateAnalyticsAdapter
from app.integrations.dhis2.errors import Dhis2Error, Dhis2NotConfiguredError
from app.integrations.dhis2.event_analytics import EventAnalyticsAdapter
from app.integrations.dhis2.http import Dhis2HttpClient
from app.integrations.dhis2.tracker import TrackerEventsAdapter
from app.integrations.dhis2.types import AggregateObservation, EventAggregateObservation, EventObservation
from app.models import (
    EventFieldMapping,
    FreshnessSnapshot,
    OrgUnit,
    OrgUnitMapping,
    Programme,
    RawAggregateValue,
    RawEventSnapshot,
    SourceMapping,
    SyncJob,
    User,
)
from app.services.authorization import AuthorizationError
from app.services.geography import descendants, resolve_org_unit_by_dhis2_uid, unmapped_dhis2_org_units
from app.services.mappings import (
    MappingSelectionError,
    resolve_programme_uid,
    select_aggregate_mappings,
    select_event_mappings,
)
from app.services.observability import record_operational_event

DHIS2_PENDING_MESSAGE = (
    "Connector implementation complete; live DHIS2 verification pending "
    "authorised endpoint configuration and credentials."
)


class SyncDispatchError(RuntimeError):
    pass


def persist_aggregate_observations(
    session: Session,
    job: SyncJob,
    observations,
    mappings_by_uid: dict[str | tuple[str, str], SourceMapping],
    extracted_at: datetime,
) -> dict[str, int]:
    stored = rejected = flagged = 0
    incoming_uids = [item.org_unit_uid for item in observations]
    unmapped = unmapped_dhis2_org_units(session, incoming_uids)
    for observation in observations:
        coc = observation.category_option_combo_uid or ""
        mapping = mappings_by_uid.get((observation.item_uid, coc))
        if mapping is None:
            mapping = mappings_by_uid.get((observation.item_uid, ""))
        if mapping is None:
            # Backwards-compatible path for callers with a single unambiguous mapping.
            mapping = mappings_by_uid.get(observation.item_uid)
        try:
            as_of = parse_period(observation.period).end
        except PeriodError:
            as_of = extracted_at.date()
        try:
            org_unit = resolve_org_unit_by_dhis2_uid(session, observation.org_unit_uid, as_of=as_of)
        except AuthorizationError:
            rejected += 1
            flagged += 1
            continue
        if mapping is None or org_unit is None:
            rejected += 1
            flagged += 1
            continue
        coc = observation.category_option_combo_uid or mapping.category_option_combo_uid or ""
        existing = session.scalar(
            select(RawAggregateValue).where(
                RawAggregateValue.source_system == MappingSourceSystem.DHIS2.value,
                RawAggregateValue.programme_id == job.programme_id,
                RawAggregateValue.org_unit_id == org_unit.id,
                RawAggregateValue.period == observation.period,
                RawAggregateValue.internal_source_key == mapping.internal_source_key,
                RawAggregateValue.category_option_combo_uid == coc,
                RawAggregateValue.is_current.is_(True),
            )
        )
        if existing is not None:
            existing.is_current = False
            session.flush()
        invalid = bool(getattr(observation, "value_invalid", False))
        absence = observation.absence_reason
        if observation.value == 0 and not invalid:
            absence = AbsenceReason.REPORTED_ZERO.value
        if invalid:
            absence = AbsenceReason.INVALID_VALUE.value
            flagged += 1
        row = RawAggregateValue(
            source_system=MappingSourceSystem.DHIS2.value,
            programme_id=job.programme_id,
            org_unit_id=org_unit.id,
            period=observation.period,
            source_metric_id=observation.item_uid,
            internal_source_key=mapping.internal_source_key,
            dhis2_org_unit_uid=observation.org_unit_uid,
            dhis2_item_uid=observation.item_uid,
            category_option_combo_uid=coc,
            value=None if invalid else observation.value,
            extracted_at=extracted_at,
            source_freshness_at=observation.source_freshness_at,
            mapping_version=mapping.mapping_version,
            sync_job_id=job.id,
            absence_reason=absence,
            checksum=observation.payload_checksum,
            is_current=True,
            value_invalid=invalid,
            provenance={"sync_job_id": str(job.id), "mapping_id": str(mapping.id)},
        )
        session.add(row)
        session.flush()
        if existing is not None:
            existing.superseded_by_id = row.id
        stored += 1
    job.stored_count = stored
    job.rejected_count = rejected
    job.flagged_count = flagged
    job.received_count = len(observations)
    if unmapped:
        job.notes = (job.notes or "") + f" Unmapped DHIS2 org units: {len(unmapped)}."
    return {"stored": stored, "rejected": rejected, "flagged": flagged, "unmapped": len(unmapped)}


def persist_event_observations(
    session: Session,
    job: SyncJob,
    observations: list[EventObservation],
    field_mappings: list[EventFieldMapping],
    extracted_at: datetime,
) -> dict[str, int]:
    stored = rejected = 0
    for observation in observations:
        if job.cancelled:
            break
        try:
            as_of = observation.occurred_at.date() if observation.occurred_at else extracted_at.date()
            org_unit = resolve_org_unit_by_dhis2_uid(session, observation.org_unit_uid, as_of=as_of)
        except AuthorizationError:
            rejected += 1
            continue
        if org_unit is None or not observation.event_uid:
            rejected += 1
            continue
        applicable = [
            row
            for row in field_mappings
            if not row.program_stage_uid or row.program_stage_uid == observation.program_stage_uid
        ]
        event_types = {row.event_type for row in applicable if row.event_type}
        if len(event_types) != 1:
            rejected += 1
            continue
        uid_to_field: dict[str, EventFieldMapping] = {}
        ambiguous = False
        for mapped in applicable:
            if not mapped.source_data_element_uid:
                continue
            previous = uid_to_field.get(mapped.source_data_element_uid)
            if previous and previous.internal_semantic_field != mapped.internal_semantic_field:
                ambiguous = True
                break
            uid_to_field[mapped.source_data_element_uid] = mapped
        if ambiguous:
            rejected += 1
            continue
        semantic: dict = {}
        for source_uid, value in (observation.data_values or {}).items():
            mapped = uid_to_field.get(source_uid)
            if mapped is None:
                continue
            if mapped.internal_semantic_field in {"name", "narrative", "username", "clinician"}:
                continue
            semantic[mapped.internal_semantic_field] = value
        semantic.setdefault("event_type", next(iter(event_types)))
        death = _as_date(semantic.get("death_date"))
        notification = _as_date(semantic.get("notification_date"))
        review = _as_date(semantic.get("review_date"))
        existing = session.scalar(
            select(RawEventSnapshot).where(
                RawEventSnapshot.event_uid == observation.event_uid,
                RawEventSnapshot.source_connector == observation.source_connector,
                RawEventSnapshot.is_current.is_(True),
            )
        )
        if existing is not None:
            existing.is_current = False
            session.flush()
        row = RawEventSnapshot(
            event_uid=observation.event_uid,
            programme_id=job.programme_id,
            source_connector=observation.source_connector,
            program_uid=observation.program_uid,
            program_stage_uid=observation.program_stage_uid,
            org_unit_id=org_unit.id,
            status=observation.status,
            occurred_at=observation.occurred_at,
            completed_at=observation.completed_at,
            source_created_at=observation.source_created_at,
            source_updated_at=observation.source_updated_at,
            death_date=death,
            notification_date=notification,
            review_date=review,
            data_values=semantic,
            extracted_at=extracted_at,
            mapping_version=job.mapping_version,
            sync_job_id=job.id,
            is_current=True,
            privacy_class="restricted_event",
        )
        session.add(row)
        session.flush()
        if existing is not None:
            existing.superseded_by_id = row.id
        stored += 1
    job.stored_count = stored
    job.rejected_count = rejected
    job.received_count = len(observations)
    return {"stored": stored, "rejected": rejected}


def _as_date(value):
    if value is None or value == "":
        return None
    from datetime import date

    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _mapped_org_unit_uids(
    session: Session, org_unit: OrgUnit, as_of=None
) -> list[str]:
    units = descendants(session, org_unit, include_self=True)
    ids = [unit.id for unit in units]
    query = select(OrgUnitMapping).where(
        OrgUnitMapping.org_unit_id.in_(ids),
        OrgUnitMapping.source_system == MappingSourceSystem.DHIS2.value,
    )
    rows = session.scalars(query).all()
    return [
        row.external_uid
        for row in rows
        if (as_of is None or not row.valid_from or row.valid_from <= as_of)
        and (as_of is None or not row.valid_to or row.valid_to >= as_of)
    ]


def _period_bounds(periods: list[str]) -> tuple[str | None, str | None]:
    if not periods:
        return None, None
    specs = [parse_period(item) for item in periods]
    start = min(item.start for item in specs)
    end = max(item.end for item in specs)
    return start.isoformat(), end.isoformat()


def _close_if_owned(http: Dhis2HttpClient, owned: bool) -> None:
    if owned:
        http.close()


def _finish(job: SyncJob, *, status: str | None = None) -> None:
    if status:
        job.status = status
    job.finished_at = datetime.now(UTC)
    if job.started_at:
        job.duration_ms = int((job.finished_at - job.started_at).total_seconds() * 1000)


def _safe_error_message(exc: Dhis2Error) -> str:
    if exc.code == "dhis2_not_configured":
        return DHIS2_PENDING_MESSAGE
    return "The connector request failed."


def enqueue_sync_job(
    session: Session,
    *,
    org_unit: OrgUnit,
    periods: list[str],
    user: User | None,
    job_type: str,
    programme_id: UUID | None,
    mapping_version: str = "v1",
    idempotency_key: str | None = None,
    window_end: date | None = None,
) -> SyncJob:
    if idempotency_key and user is not None:
        existing = session.scalar(
            select(SyncJob).where(
                SyncJob.idempotency_key == idempotency_key,
                SyncJob.initiated_by_user_id == user.id,
            )
        )
        if existing is not None:
            return existing
    job = SyncJob(
        id=uuid4(),
        job_type=job_type,
        status=JobStatus.QUEUED.value,
        org_unit_id=org_unit.id,
        programme_id=programme_id,
        period_from=periods[0] if periods else None,
        period_to=periods[-1] if periods else None,
        mapping_version=mapping_version,
        initiated_by_user_id=user.id if user else None,
        idempotency_key=idempotency_key,
        window_end=window_end,
    )
    session.add(job)
    session.flush()
    return job


def execute_sync_job(session: Session, job_id: UUID, client: Dhis2HttpClient | None = None) -> SyncJob:
    job = session.get(SyncJob, job_id)
    if job is None:
        raise ValueError("Sync job not found.")
    session.refresh(job)
    if job.cancelled or job.status == JobStatus.CANCELLED.value:
        job.status = JobStatus.CANCELLED.value
        _finish(job)
        session.flush()
        return job
    if job.status not in {JobStatus.QUEUED.value, JobStatus.FAILED.value}:
        return job
    job.status = JobStatus.RUNNING.value
    job.started_at = datetime.now(UTC)
    session.flush()
    org_unit = session.get(OrgUnit, job.org_unit_id) if job.org_unit_id else None
    if org_unit is None:
        job.status = JobStatus.FAILED.value
        job.error_code = "invalid_geography"
        job.error_message = "Organisation unit is not available for this job."
        _finish(job)
        session.flush()
        return job
    periods = [item for item in [job.period_from, job.period_to] if item]
    if job.period_from and job.period_to and job.period_from == job.period_to:
        periods = [job.period_from]
    elif job.period_from and not job.period_to:
        periods = [job.period_from]
    try:
        if job.job_type == ConnectorType.TRACKER.value:
            return _run_tracker(session, job, org_unit, periods, client)
        if job.job_type == ConnectorType.EVENT_ANALYTICS_QUERY.value:
            return _run_event_analytics(session, job, org_unit, periods, client)
        if job.job_type == ConnectorType.EVENT_ANALYTICS_AGGREGATE.value:
            return _run_event_analytics_aggregate(session, job, org_unit, periods, client)
        if job.job_type == ConnectorType.AGGREGATE.value:
            return _run_aggregate(session, job, org_unit, periods, client)
        job.status = JobStatus.FAILED.value
        job.error_code = "invalid_job_type"
        job.error_message = "The stored sync job type is not supported."
        _finish(job)
        session.flush()
        return job
    except MappingSelectionError as exc:
        job.status = JobStatus.FAILED.value
        job.error_code = exc.code
        job.error_message = exc.message
        _finish(job)
        session.flush()
        return job


def _run_aggregate(
    session: Session,
    job: SyncJob,
    org_unit: OrgUnit,
    periods: list[str],
    client: Dhis2HttpClient | None,
) -> SyncJob:
    if job.programme_id is None:
        job.status = JobStatus.FAILED.value
        job.error_code = "mapping_missing"
        job.error_message = "An authorised programme is required to select mappings."
        _finish(job)
        session.flush()
        return job
    as_of = parse_period(periods[0]).start if periods else None
    mappings = select_aggregate_mappings(
        session,
        programme_id=job.programme_id,
        mapping_version=job.mapping_version or "v1",
        as_of=as_of,
    )
    job.requested_count = len(mappings) * max(len(periods), 1)
    if not mappings:
        job.status = JobStatus.FAILED.value
        job.error_code = "mapping_missing"
        job.error_message = "No enabled mappings are valid for the requested programme and version."
        _finish(job)
        session.flush()
        return job
    owned = client is None
    http = client or Dhis2HttpClient(cancelled=lambda: _cancelled(session, job.id))
    try:
        adapter = AggregateAnalyticsAdapter(http)
        ou_uids = _mapped_org_unit_uids(session, org_unit, as_of)
        observations = adapter.fetch(
            dx_uids=[row.dhis2_item_uid for row in mappings if row.dhis2_item_uid],
            org_unit_uids=ou_uids,
            periods=periods,
        )
        by_uid = {
            (row.dhis2_item_uid, row.category_option_combo_uid or ""): row
            for row in mappings
            if row.dhis2_item_uid
        }
        counts = persist_aggregate_observations(session, job, observations, by_uid, datetime.now(UTC))
        job.retry_count = http.last_retry_count
        if _cancelled(session, job.id):
            job.status = JobStatus.CANCELLED.value
        elif counts["rejected"]:
            job.status = JobStatus.PARTIALLY_SUCCEEDED.value
        else:
            job.status = JobStatus.SUCCEEDED.value
        job.source_freshness_at = _oldest_freshness(observations)
    except Dhis2NotConfiguredError:
        job.status = JobStatus.FAILED.value
        job.error_code = "dhis2_not_configured"
        job.error_message = DHIS2_PENDING_MESSAGE
    except Dhis2Error as exc:
        job.status = JobStatus.FAILED.value
        job.error_code = exc.code
        job.error_message = _safe_error_message(exc)
        job.retry_count = http.last_retry_count
    finally:
        _close_if_owned(http, owned)
    _finish(job)
    _record_freshness(session, "aggregate", job)
    record_operational_event(
        "sync_complete",
        job_id=str(job.id),
        duration_ms=job.duration_ms,
        records_received=job.received_count,
        records_stored=job.stored_count,
        records_rejected=job.rejected_count,
        retry_count=job.retry_count,
        session=session,
    )
    session.flush()
    return job


def _run_tracker(
    session: Session,
    job: SyncJob,
    org_unit: OrgUnit,
    periods: list[str],
    client: Dhis2HttpClient | None,
) -> SyncJob:
    if job.programme_id is None:
        return _fail_mapping(session, job)
    as_of = parse_period(periods[0]).start if periods else None
    mappings = select_event_mappings(
        session,
        programme_id=job.programme_id,
        mapping_version=job.mapping_version or "v1",
        as_of=as_of,
    )
    program_uid = resolve_programme_uid(
        session, job.programme_id, job.mapping_version or "v1", as_of=as_of
    )
    if not program_uid:
        return _fail_mapping(session, job)
    occurred_after, occurred_before = _period_bounds(periods)
    if job.window_end is not None and occurred_before is not None:
        # An explicit, validated window end extends retrieval through the extraction date.
        occurred_before = max(job.window_end.isoformat(), occurred_before)
    job.window_start = date.fromisoformat(occurred_after) if occurred_after else None
    job.window_end = date.fromisoformat(occurred_before) if occurred_before else None
    owned = client is None
    http = client or Dhis2HttpClient(cancelled=lambda: _cancelled(session, job.id))
    try:
        adapter = TrackerEventsAdapter(http)
        ou_uids = _mapped_org_unit_uids(session, org_unit, as_of)
        result = adapter.fetch_events_result(
            program_uid=program_uid,
            org_unit_uids=ou_uids,
            occurred_after=occurred_after,
            occurred_before=occurred_before,
        )
        persist_event_observations(session, job, result.observations, mappings, datetime.now(UTC))
        job.retry_count = http.last_retry_count
        job.page_limit_reached = result.page_limit_reached
        if _cancelled(session, job.id):
            job.status = JobStatus.CANCELLED.value
        elif result.page_limit_reached:
            job.status = JobStatus.PARTIALLY_SUCCEEDED.value
            job.error_code = "page_limit_reached"
            job.error_message = "Configured page limit was reached before the tracker retrieval completed."
        elif job.rejected_count:
            job.status = JobStatus.PARTIALLY_SUCCEEDED.value
        else:
            job.status = JobStatus.SUCCEEDED.value
    except Dhis2NotConfiguredError:
        job.status = JobStatus.FAILED.value
        job.error_code = "dhis2_not_configured"
        job.error_message = DHIS2_PENDING_MESSAGE
    except Dhis2Error as exc:
        job.status = JobStatus.FAILED.value
        job.error_code = exc.code
        job.error_message = _safe_error_message(exc)
        job.retry_count = http.last_retry_count
    finally:
        _close_if_owned(http, owned)
    _finish(job)
    if job.status == JobStatus.SUCCEEDED.value:
        # Tracker returns current operational state: the extraction time is its freshness.
        job.source_freshness_at = job.finished_at
    _record_freshness(session, "tracker", job)
    session.flush()
    return job


def _run_event_analytics(
    session: Session,
    job: SyncJob,
    org_unit: OrgUnit,
    periods: list[str],
    client: Dhis2HttpClient | None,
) -> SyncJob:
    if job.programme_id is None:
        return _fail_mapping(session, job)
    as_of = parse_period(periods[0]).start if periods else None
    mappings = select_event_mappings(
        session,
        programme_id=job.programme_id,
        mapping_version=job.mapping_version or "v1",
        as_of=as_of,
    )
    program_uid = resolve_programme_uid(
        session, job.programme_id, job.mapping_version or "v1", as_of=as_of
    )
    if not program_uid:
        return _fail_mapping(session, job)
    owned = client is None
    http = client or Dhis2HttpClient(cancelled=lambda: _cancelled(session, job.id))
    try:
        adapter = EventAnalyticsAdapter(http)
        ou_uids = _mapped_org_unit_uids(session, org_unit, as_of)
        observations = adapter.query_events(program_uid=program_uid, org_unit_uids=ou_uids, periods=periods)
        persist_event_observations(session, job, observations, mappings, datetime.now(UTC))
        job.retry_count = http.last_retry_count
        job.page_limit_reached = adapter.page_limit_reached
        if adapter.page_limit_reached:
            job.status = JobStatus.PARTIALLY_SUCCEEDED.value
            job.error_code = "page_limit_reached"
            job.error_message = "Configured page limit was reached before event analytics completed."
        elif job.rejected_count:
            job.status = JobStatus.PARTIALLY_SUCCEEDED.value
        else:
            job.status = JobStatus.SUCCEEDED.value
    except Dhis2NotConfiguredError:
        job.status = JobStatus.FAILED.value
        job.error_code = "dhis2_not_configured"
        job.error_message = DHIS2_PENDING_MESSAGE
    except Dhis2Error as exc:
        job.status = JobStatus.FAILED.value
        job.error_code = exc.code
        job.error_message = _safe_error_message(exc)
    finally:
        _close_if_owned(http, owned)
    _finish(job)
    _record_freshness(session, "event_analytics_query", job)
    session.flush()
    return job


def persist_event_aggregate_observations(
    session: Session,
    job: SyncJob,
    observations: list[EventAggregateObservation],
    extracted_at: datetime,
) -> dict[str, int]:
    converted = [
        AggregateObservation(
            org_unit_uid=item.org_unit_uid,
            period=item.period,
            item_uid=item.metric,
            value=item.value,
            source_freshness_at=item.source_freshness_at,
        )
        for item in observations
    ]
    if job.programme_id is None:
        mappings: list[SourceMapping] = []
    else:
        as_of = parse_period(job.period_from).start if job.period_from else None
        mappings = select_aggregate_mappings(
            session,
            programme_id=job.programme_id,
            mapping_version=job.mapping_version or "v1",
            as_of=as_of,
        )
    by_uid = {
        (row.dhis2_item_uid, row.category_option_combo_uid or ""): row
        for row in mappings
        if row.dhis2_item_uid
    }
    return persist_aggregate_observations(session, job, converted, by_uid, extracted_at)


def _run_event_analytics_aggregate(
    session: Session,
    job: SyncJob,
    org_unit: OrgUnit,
    periods: list[str],
    client: Dhis2HttpClient | None,
) -> SyncJob:
    if job.programme_id is None:
        return _fail_mapping(session, job)
    as_of = parse_period(periods[0]).start if periods else None
    program_uid = resolve_programme_uid(
        session, job.programme_id, job.mapping_version or "v1", as_of=as_of
    )
    if not program_uid:
        return _fail_mapping(session, job)
    owned = client is None
    http = client or Dhis2HttpClient(cancelled=lambda: _cancelled(session, job.id))
    try:
        adapter = EventAnalyticsAdapter(http)
        ou_uids = _mapped_org_unit_uids(session, org_unit, as_of)
        observations = adapter.aggregate(program_uid=program_uid, org_unit_uids=ou_uids, periods=periods)
        persist_event_aggregate_observations(session, job, observations, datetime.now(UTC))
        job.retry_count = http.last_retry_count
        job.status = JobStatus.SUCCEEDED.value if job.rejected_count == 0 else JobStatus.PARTIALLY_SUCCEEDED.value
        job.source_freshness_at = _oldest_freshness(observations)
    except Dhis2NotConfiguredError:
        job.status = JobStatus.FAILED.value
        job.error_code = "dhis2_not_configured"
        job.error_message = DHIS2_PENDING_MESSAGE
    except Dhis2Error as exc:
        job.status = JobStatus.FAILED.value
        job.error_code = exc.code
        job.error_message = _safe_error_message(exc)
    finally:
        _close_if_owned(http, owned)
    _finish(job)
    _record_freshness(session, "event_analytics_aggregate", job)
    session.flush()
    return job


def run_aggregate_sync(
    session: Session,
    *,
    org_unit: OrgUnit,
    periods: list[str],
    user: User | None,
    client: Dhis2HttpClient | None = None,
    programme_id: UUID | None = None,
) -> SyncJob:
    if programme_id is None:
        programme = session.scalar(select(Programme).where(Programme.code == "MNCH"))
        programme_id = programme.id if programme else None
    job = enqueue_sync_job(
        session,
        org_unit=org_unit,
        periods=periods,
        user=user,
        job_type=ConnectorType.AGGREGATE.value,
        programme_id=programme_id,
    )
    return execute_sync_job(session, job.id, client=client)


def run_tracker_sync(
    session: Session,
    *,
    org_unit: OrgUnit,
    program_uid: str | None = None,
    user: User | None = None,
    client: Dhis2HttpClient | None = None,
    programme_id: UUID | None = None,
    periods: list[str] | None = None,
) -> SyncJob:
    del program_uid
    job = enqueue_sync_job(
        session,
        org_unit=org_unit,
        periods=periods or [],
        user=user,
        job_type=ConnectorType.TRACKER.value,
        programme_id=programme_id,
    )
    return execute_sync_job(session, job.id, client=client)


def run_event_analytics_sync(
    session: Session,
    *,
    org_unit: OrgUnit,
    program_uid: str | None = None,
    periods: list[str],
    user: User | None,
    client: Dhis2HttpClient | None = None,
    programme_id: UUID | None = None,
) -> SyncJob:
    del program_uid
    job = enqueue_sync_job(
        session,
        org_unit=org_unit,
        periods=periods,
        user=user,
        job_type=ConnectorType.EVENT_ANALYTICS_QUERY.value,
        programme_id=programme_id,
    )
    return execute_sync_job(session, job.id, client=client)


def run_event_analytics_aggregate_sync(
    session: Session,
    *,
    org_unit: OrgUnit,
    program_uid: str | None = None,
    periods: list[str],
    user: User | None,
    client: Dhis2HttpClient | None = None,
    programme_id: UUID | None = None,
) -> SyncJob:
    del program_uid
    job = enqueue_sync_job(
        session,
        org_unit=org_unit,
        periods=periods,
        user=user,
        job_type=ConnectorType.EVENT_ANALYTICS_AGGREGATE.value,
        programme_id=programme_id,
    )
    return execute_sync_job(session, job.id, client=client)


def run_sync_job(
    session: Session,
    *,
    org_unit: OrgUnit,
    periods: list[str],
    user: User | None,
    job_type: str = "aggregate",
    program_uid: str | None = None,
    client: Dhis2HttpClient | None = None,
    programme_id: UUID | None = None,
    mapping_version: str = "v1",
    idempotency_key: str | None = None,
) -> SyncJob:
    del program_uid
    job = enqueue_sync_job(
        session,
        org_unit=org_unit,
        periods=periods,
        user=user,
        job_type=job_type,
        programme_id=programme_id,
        mapping_version=mapping_version,
        idempotency_key=idempotency_key,
    )
    return execute_sync_job(session, job.id, client=client)


def dispatch_sync_job(job_id: UUID) -> None:
    settings = get_settings()
    if settings.app_env == "test" or settings.sync_execution == "eager":
        return
    try:
        from app.workers.tasks import execute_sync_job_task

        execute_sync_job_task.delay(str(job_id))
    except Exception as exc:  # noqa: BLE001
        record_operational_event("sync_enqueue_failed", job_id=str(job_id))
        raise SyncDispatchError("The sync job could not be submitted to the worker queue.") from exc


def should_run_eager() -> bool:
    settings = get_settings()
    return settings.app_env == "test" or settings.sync_execution == "eager"


def _cancelled(session: Session, job_id: UUID) -> bool:
    job = session.get(SyncJob, job_id)
    return bool(job and job.cancelled)


def _fail_mapping(session: Session, job: SyncJob) -> SyncJob:
    job.status = JobStatus.FAILED.value
    job.error_code = "mapping_missing"
    job.error_message = "A programme UID must be resolved from authorised mappings."
    _finish(job)
    session.flush()
    return job


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _oldest_freshness(observations) -> datetime | None:
    """Deterministic source freshness: the oldest reported freshness across the extraction."""
    values = [_aware(item.source_freshness_at) for item in observations if item.source_freshness_at]
    return min(values) if values else None


def _record_freshness(session: Session, connector: str, job: SyncJob) -> FreshnessSnapshot:
    """Write freshness only after the job has a final status, finished_at and duration.

    ``last_success_at``, ``source_freshness_at``, ``lag_seconds`` and ``sync_job_id`` always
    describe the same successful job. ``status`` and ``detail.last_attempt`` describe the
    latest attempt, so a later failure never overwrites the last successful timestamps.
    """
    if job.finished_at is None:
        raise ValueError("Freshness must be recorded after the sync job has finished.")
    row = session.scalar(select(FreshnessSnapshot).where(FreshnessSnapshot.connector == connector))
    if row is None:
        row = FreshnessSnapshot(connector=connector, status="unknown")
        session.add(row)
    detail = dict(row.detail or {})
    detail["last_attempt"] = {
        "sync_job_id": str(job.id),
        "status": job.status,
        "finished_at": _aware(job.finished_at).isoformat(),
        "error_code": job.error_code,
    }
    row.detail = detail
    row.status = job.status
    if job.status == JobStatus.SUCCEEDED.value:
        finished = _aware(job.finished_at)
        freshness = _aware(job.source_freshness_at)
        row.last_success_at = finished
        row.source_freshness_at = freshness
        row.sync_job_id = job.id
        row.lag_seconds = int((finished - freshness).total_seconds()) if freshness else None
    session.flush()
    return row

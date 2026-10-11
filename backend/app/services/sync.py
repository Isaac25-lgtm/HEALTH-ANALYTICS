from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import and_, case, or_, select, text, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain.enums import (
    AbsenceReason,
    ActionPermission,
    ConnectorType,
    JobStatus,
    MappingSourceSystem,
    OrgUnitLevel,
)
from app.domain.mpdsr_minimisation import minimise_event_values
from app.domain.periods import PeriodError, parse_period
from app.integrations.dhis2.aggregate import AggregateAnalyticsAdapter
from app.integrations.dhis2.errors import (
    Dhis2Error,
    Dhis2NotConfiguredError,
    Dhis2ValidationError,
)
from app.integrations.dhis2.event_analytics import EventAnalyticsAdapter
from app.integrations.dhis2.gates import Dhis2Disabled, ensure_extraction_enabled
from app.integrations.dhis2.http import Dhis2HttpClient
from app.integrations.dhis2.periods import PeriodTranslation, covering_internal_period
from app.integrations.dhis2.periods import translate as translate_period
from app.integrations.dhis2.tracker import TrackerEventsAdapter, TrackerFetchResult
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
from app.services.authorization import (
    AuthorizationError,
    is_descendant_or_self,
    require_action,
    require_org_unit_access,
    require_programme_access,
)
from app.services.geography import (
    descendants,
    mapping_in_force,
    resolve_org_unit_by_dhis2_uid,
    unmapped_dhis2_org_units,
)
from app.services.hierarchy_authority import DISTRICT_CITY_COHORT
from app.services.mapping_coverage import evaluate_coverage
from app.services.mappings import (
    MappingSelectionError,
    resolve_programme_uid,
    select_aggregate_mappings,
    select_event_mappings,
)
from app.services.observability import record_operational_event

DHIS2_PENDING_MESSAGE = (
    "DHIS2 is not configured for this deployment: a base URL and credentials are required "
    "before any extraction can run."
)


class SyncDispatchError(RuntimeError):
    pass


def persist_aggregate_observations(
    session: Session,
    job: SyncJob,
    observations,
    mappings_by_uid: dict[str | tuple[str, str], SourceMapping],
    extracted_at: datetime,
    *,
    seen_row_ids: set[UUID] | None = None,
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
        scope = session.get(OrgUnit, job.org_unit_id) if job.org_unit_id else None
        if (
            mapping is None
            or org_unit is None
            or mapping.programme_id != job.programme_id
            or (scope is not None and not is_descendant_or_self(org_unit, scope))
        ):
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
            provenance={
                "sync_job_id": str(job.id),
                "mapping_id": str(mapping.id),
                "source_periods": list(observation.source_periods or (observation.period,)),
            },
        )
        session.add(row)
        session.flush()
        if existing is not None:
            existing.superseded_by_id = row.id
        if seen_row_ids is not None:
            seen_row_ids.add(row.id)
        stored += 1
    job.stored_count = stored
    job.rejected_count = rejected
    job.flagged_count = flagged
    job.received_count = len(observations)
    if unmapped:
        job.notes = (job.notes or "") + f" Unmapped DHIS2 org units: {len(unmapped)}."
    return {"stored": stored, "rejected": rejected, "flagged": flagged, "unmapped": len(unmapped)}


EVENT_DATE_SOURCE = "occurredAt"


_EVENT_COMPARED_FIELDS = (
    "programme_id",
    "program_uid",
    "program_stage_uid",
    "org_unit_id",
    "status",
    "death_date",
    "notification_date",
    "review_date",
    "data_values",
    "mapping_version",
)
_EVENT_COMPARED_INSTANTS = ("occurred_at", "completed_at", "source_created_at", "source_updated_at")
_EVENT_CHUNK = 1000


def _same_moment(stored: datetime | None, incoming: datetime | None) -> bool:
    if stored is None or incoming is None:
        return stored is None and incoming is None
    if incoming.tzinfo is None:
        # DHIS2 sends local timestamps without an offset. The database returns the same wall-clock
        # time it was given, labelled with the session time zone, so the labels are not compared.
        return stored.replace(tzinfo=None) == incoming
    return _aware(stored) == incoming


def _event_unchanged(current: RawEventSnapshot, values: dict) -> bool:
    """True when a re-extracted event carries exactly what the current snapshot already holds."""
    return all(getattr(current, name) == values[name] for name in _EVENT_COMPARED_FIELDS) and all(
        _same_moment(getattr(current, name), values[name]) for name in _EVENT_COMPARED_INSTANTS
    )


class _EventOrgUnits:
    """Organisation units of one extraction, resolved from two queries instead of two per event."""

    def __init__(self, session: Session, uids: set[str]) -> None:
        self._mappings: dict[str, list[OrgUnitMapping]] = {}
        ordered = sorted(uid for uid in uids if uid)
        for start in range(0, len(ordered), 5000):
            for row in session.scalars(
                select(OrgUnitMapping).where(
                    OrgUnitMapping.source_system == MappingSourceSystem.DHIS2.value,
                    OrgUnitMapping.external_uid.in_(ordered[start : start + 5000]),
                )
            ):
                self._mappings.setdefault(row.external_uid, []).append(row)
        unit_ids = sorted({row.org_unit_id for rows in self._mappings.values() for row in rows}, key=str)
        self._units: dict[UUID, OrgUnit] = {}
        for start in range(0, len(unit_ids), 5000):
            for unit in session.scalars(select(OrgUnit).where(OrgUnit.id.in_(unit_ids[start : start + 5000]))):
                self._units[unit.id] = unit

    def resolve(self, uid: str, as_of: date) -> OrgUnit | None:
        in_force = [row for row in self._mappings.get(uid, []) if mapping_in_force(row, as_of)]
        if len(in_force) > 1:
            raise AuthorizationError(
                "invalid_input",
                "Overlapping active DHIS2 organisation-unit mappings exist for the requested source UID.",
            )
        if not in_force:
            return None
        return self._units.get(in_force[0].org_unit_id)


def persist_event_observations(
    session: Session,
    job: SyncJob,
    observations: list[EventObservation],
    field_mappings: list[EventFieldMapping],
    extracted_at: datetime,
    *,
    seen_row_ids: set[UUID] | None = None,
) -> dict[str, int]:
    """Store one extraction of events in bulk.

    An event whose minimised content is identical to its current snapshot is not copied again: the
    snapshot is marked as re-extracted (``extracted_at`` and the verifying job). Only new or changed
    events create a snapshot, which supersedes the previous one. A national refresh is therefore a
    few bulk statements, not five statements for every event.
    """
    stored = rejected = dropped_fields = missing_death_dates = 0
    scope = session.get(OrgUnit, job.org_unit_id) if job.org_unit_id else None
    org_units = _EventOrgUnits(session, {observation.org_unit_uid for observation in observations})
    # The last occurrence of an event within one extraction is the one kept.
    prepared: dict[tuple[str, str], dict] = {}
    for observation in observations:
        if job.cancelled:
            break
        try:
            as_of = observation.occurred_at.date() if observation.occurred_at else extracted_at.date()
            org_unit = org_units.resolve(observation.org_unit_uid, as_of)
        except AuthorizationError:
            rejected += 1
            continue
        if org_unit is None or not observation.event_uid:
            rejected += 1
            continue
        if scope is not None and not is_descendant_or_self(org_unit, scope):
            rejected += 1
            continue
        applicable = [
            row
            for row in field_mappings
            if (not row.program_stage_uid or row.program_stage_uid == observation.program_stage_uid)
            and (not row.program_uid or row.program_uid == observation.program_uid)
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
        mapped_values: dict = {}
        for source_uid, value in (observation.data_values or {}).items():
            mapped = uid_to_field.get(source_uid)
            if mapped is None:
                continue
            mapped_values[mapped.internal_semantic_field] = value
        # A form's own event date (for example the date of review) is mapped with the reserved
        # source ``occurredAt``; it is a date, never an identifier.
        event_date_field = uid_to_field.get(EVENT_DATE_SOURCE)
        if event_date_field is not None and observation.occurred_at is not None:
            mapped_values[event_date_field.internal_semantic_field] = observation.occurred_at.isoformat()
        # Whitelist minimisation: only approved, non-identifying scalar facts are persisted.
        minimised = minimise_event_values(mapped_values)
        semantic = minimised.values
        dropped_fields += minimised.dropped_count
        semantic.setdefault("event_type", next(iter(event_types)))
        death = _as_date(semantic.get("death_date"))
        if death is None:
            missing_death_dates += 1
        prepared[(observation.event_uid, observation.source_connector)] = {
            "event_uid": observation.event_uid,
            "programme_id": job.programme_id,
            "source_connector": observation.source_connector,
            "program_uid": observation.program_uid,
            "program_stage_uid": observation.program_stage_uid,
            "org_unit_id": org_unit.id,
            "status": observation.status,
            "occurred_at": observation.occurred_at,
            "completed_at": observation.completed_at,
            "source_created_at": observation.source_created_at,
            "source_updated_at": observation.source_updated_at,
            "death_date": death,
            "notification_date": _as_date(semantic.get("notification_date")),
            "review_date": _as_date(semantic.get("review_date")),
            "data_values": semantic,
            "mapping_version": job.mapping_version,
        }
        stored += 1
    keys = list(prepared)
    for start in range(0, len(keys), _EVENT_CHUNK):
        chunk = keys[start : start + _EVENT_CHUNK]
        current_rows = {
            (row.event_uid, row.source_connector): row
            for row in session.scalars(
                select(RawEventSnapshot).where(
                    RawEventSnapshot.event_uid.in_([event_uid for event_uid, _connector in chunk]),
                    RawEventSnapshot.is_current.is_(True),
                )
            )
        }
        verified_ids: list[UUID] = []
        replaced: list[tuple[UUID, RawEventSnapshot]] = []
        created: list[RawEventSnapshot] = []
        for key in chunk:
            values = prepared[key]
            current = current_rows.get(key)
            if current is not None and _event_unchanged(current, values):
                verified_ids.append(current.id)
                continue
            row = RawEventSnapshot(
                id=uuid4(),
                **values,
                extracted_at=extracted_at,
                sync_job_id=job.id,
                is_current=True,
                privacy_class="restricted_event",
            )
            created.append(row)
            if current is not None:
                replaced.append((current.id, row))
        if verified_ids:
            session.execute(
                update(RawEventSnapshot)
                .where(RawEventSnapshot.id.in_(verified_ids))
                .values(extracted_at=extracted_at, sync_job_id=job.id)
                .execution_options(synchronize_session=False)
            )
        # The current-row unique index allows one current snapshot per event: retire, then insert.
        # Whole-chunk statements: the revision trigger and the database work per statement.
        if replaced:
            session.execute(
                update(RawEventSnapshot)
                .where(RawEventSnapshot.id.in_([current_id for current_id, _row in replaced]))
                .values(is_current=False)
                .execution_options(synchronize_session=False)
            )
        session.add_all(created)
        session.flush()
        if replaced:
            successor = {current_id: row.id for current_id, row in replaced}
            session.execute(
                update(RawEventSnapshot)
                .where(RawEventSnapshot.id.in_(list(successor)))
                .values(superseded_by_id=case(successor, value=RawEventSnapshot.id))
                .execution_options(synchronize_session=False)
            )
        if seen_row_ids is not None:
            seen_row_ids.update(verified_ids)
            seen_row_ids.update(row.id for row in created)
    job.stored_count = stored
    job.rejected_count = rejected
    job.received_count = len(observations)
    if dropped_fields:
        # Counts only: which unapproved fields arrived is not recorded, and their values never are.
        record_operational_event(
            "mpdsr_event_fields_dropped",
            job_id=str(job.id),
            records_rejected=dropped_fields,
        )
    return {
        "stored": stored,
        "rejected": rejected,
        "dropped_fields": dropped_fields,
        "missing_death_dates": missing_death_dates,
    }


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


class OrgScopeError(RuntimeError):
    """The request scope could not be proven, so no request may be made."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _mapped_org_unit_uids(session: Session, org_unit: OrgUnit, as_of=None) -> list[str]:
    """Resolve a complete, non-overlapping DHIS2 request cohort or fail closed.

    Country and regional requests use district/city peers, never a mixture of parents and
    descendants.  Uganda is only a valid country scope when the approved 146-unit cohort is
    present.  Every target must have exactly one effective mapping and every UID must identify
    exactly one target.  This prevents a successful one-district extraction being presented as
    national data.
    """
    subtree = descendants(session, org_unit, include_self=True)
    if as_of is not None:
        subtree = [
            unit
            for unit in subtree
            if (unit.valid_from is None or unit.valid_from <= as_of)
            and (unit.valid_to is None or unit.valid_to >= as_of)
        ]
    if org_unit.level_type in {
        OrgUnitLevel.COUNTRY.value,
        OrgUnitLevel.REGION.value,
        OrgUnitLevel.SUB_REGION.value,
    }:
        units = [unit for unit in subtree if unit.level_type in {OrgUnitLevel.DISTRICT.value, OrgUnitLevel.CITY.value}]
        if org_unit.level_type == OrgUnitLevel.COUNTRY.value and len(units) != DISTRICT_CITY_COHORT:
            raise OrgScopeError(
                "org_hierarchy_incomplete",
                "The Uganda request is blocked because the active district/city hierarchy is "
                f"not the approved {DISTRICT_CITY_COHORT}-unit cohort.",
            )
        if not units:
            raise OrgScopeError(
                "org_hierarchy_incomplete",
                "The requested geography has no active district/city cohort, so its DHIS2 "
                "request scope cannot be proven.",
            )
    elif org_unit.level_type in {
        OrgUnitLevel.DISTRICT.value,
        OrgUnitLevel.CITY.value,
        OrgUnitLevel.SUB_COUNTY.value,
        OrgUnitLevel.FACILITY.value,
    }:
        units = [org_unit]
    else:
        raise OrgScopeError(
            "org_hierarchy_unsupported",
            "The requested geography level cannot be translated into a safe DHIS2 scope.",
        )

    ids = [unit.id for unit in units]
    query = select(OrgUnitMapping).where(
        OrgUnitMapping.org_unit_id.in_(ids),
        OrgUnitMapping.source_system == MappingSourceSystem.DHIS2.value,
    )
    rows = session.scalars(query).all()
    effective = [
        row
        for row in rows
        if (as_of is None or row.valid_from is None or row.valid_from <= as_of)
        and (as_of is None or row.valid_to is None or row.valid_to >= as_of)
    ]
    if not effective:
        raise OrgScopeError(
            "org_mapping_missing",
            "No approved DHIS2 organisation-unit mapping covers the requested geography, "
            "so the request scope cannot be proven.",
        )
    by_unit: dict[UUID, list[OrgUnitMapping]] = {unit.id: [] for unit in units}
    for row in effective:
        by_unit[row.org_unit_id].append(row)
    missing = sum(1 for mappings in by_unit.values() if not mappings)
    ambiguous = sum(1 for mappings in by_unit.values() if len(mappings) > 1)
    if missing:
        raise OrgScopeError(
            "org_mapping_incomplete",
            f"The DHIS2 geography mapping is incomplete for {missing} unit(s) in the requested "
            "cohort; no partial extraction was started.",
        )
    if ambiguous:
        raise OrgScopeError(
            "org_mapping_ambiguous",
            f"The DHIS2 geography mapping has multiple effective mappings for {ambiguous} "
            "unit(s); no extraction was started.",
        )
    uids = [by_unit[unit.id][0].external_uid for unit in units]
    if len(set(uids)) != len(uids):
        raise OrgScopeError(
            "org_mapping_ambiguous",
            "A DHIS2 organisation-unit UID is assigned to more than one unit in the requested "
            "cohort; no extraction was started.",
        )
    return uids


def _aggregate_level_uids(session: Session, org_unit: OrgUnit, as_of=None) -> list[str]:
    """Mapped DHIS2 UIDs of the requested unit and any region-level units beneath it.

    Used only for DHIS2 indicators, whose national and regional values must come from DHIS2
    itself. District-level and lower requests need nothing extra.
    """
    if org_unit.level_type not in {
        OrgUnitLevel.COUNTRY.value,
        OrgUnitLevel.REGION.value,
        OrgUnitLevel.SUB_REGION.value,
    }:
        return []
    units = [
        unit
        for unit in descendants(session, org_unit, include_self=True)
        if unit.level_type in {OrgUnitLevel.COUNTRY.value, OrgUnitLevel.REGION.value, OrgUnitLevel.SUB_REGION.value}
    ]
    rows = session.scalars(
        select(OrgUnitMapping).where(
            OrgUnitMapping.org_unit_id.in_([unit.id for unit in units]),
            OrgUnitMapping.source_system == MappingSourceSystem.DHIS2.value,
        )
    ).all()
    uids = [
        row.external_uid
        for row in rows
        if (as_of is None or row.valid_from is None or row.valid_from <= as_of)
        and (as_of is None or row.valid_to is None or row.valid_to >= as_of)
    ]
    return sorted(set(uids))


def _period_bounds(periods: list[str]) -> tuple[str | None, str | None]:
    if not periods:
        return None, None
    specs = [parse_period(item) for item in periods]
    start = min(item.start for item in specs)
    end = max(item.end for item in specs)
    return start.isoformat(), end.isoformat()


def _event_native_periods(periods: list[str]) -> list[str]:
    """Translate internal event-analysis periods without changing their boundaries."""
    native: list[str] = []
    for period in dict.fromkeys(periods):
        translation = translate_period(period, aggregation_semantics="COUNT")
        native.extend(translation.dhis2_periods)
    return list(dict.fromkeys(native))


def _normalise_event_aggregate_periods(
    observations: list[EventAggregateObservation], internal_period: str
) -> list[EventAggregateObservation]:
    """Put event-aggregate responses back under the HPIP period key."""
    translation = translate_period(internal_period, aggregation_semantics="COUNT")
    unexpected = [
        item.period for item in observations if not covering_internal_period(item.period, translation.internal_key)
    ]
    if unexpected:
        raise Dhis2ValidationError(f"DHIS2 returned {len(unexpected)} event rows outside {translation.internal_key}.")
    return [
        EventAggregateObservation(
            org_unit_uid=item.org_unit_uid,
            period=translation.internal_key,
            metric=item.metric,
            value=item.value,
            source_freshness_at=item.source_freshness_at,
            source_periods=(item.period,),
        )
        for item in observations
    ]


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


def _sync_lock_key(job_id: UUID) -> int:
    return int.from_bytes(job_id.bytes[:8], byteorder="big", signed=True)


@contextmanager
def sync_job_execution_lock(session: Session, job_id: UUID) -> Iterator[bool]:
    """Hold a PostgreSQL session lock for the complete network execution.

    The lock is deliberately held on a dedicated connection. A worker crash closes that
    connection, so a redelivery can reclaim a row left in ``running``. SQLite test/eager mode
    remains guarded by the conditional status update in :func:`claim_sync_job`.
    """
    bind = session.get_bind()
    if bind.dialect.name != "postgresql":
        yield True
        return
    key = _sync_lock_key(job_id)
    connection = bind.connect()
    acquired = bool(connection.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": key}).scalar())
    try:
        yield acquired
    finally:
        if acquired:
            connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
        connection.close()


def claim_sync_job(
    session: Session,
    job_id: UUID,
    *,
    reclaim_running: bool = False,
) -> bool:
    """Durably claim one queued delivery before network I/O.

    The conditional update is the concurrency guard: duplicate Celery deliveries cannot both
    enter extraction. A failed row is reclaimed only for the explicit internal-error retry path.
    """
    now = datetime.now(UTC)
    statuses = [SyncJob.status == JobStatus.QUEUED.value]
    if reclaim_running:
        statuses.append(SyncJob.status == JobStatus.RUNNING.value)
    result = session.execute(
        update(SyncJob)
        .where(
            SyncJob.id == job_id,
            or_(
                *statuses,
                and_(
                    SyncJob.status == JobStatus.FAILED.value,
                    SyncJob.error_code == "internal_sync_error",
                ),
            ),
            SyncJob.cancelled.is_(False),
        )
        .values(
            status=JobStatus.RUNNING.value,
            started_at=now,
            finished_at=None,
            error_code=None,
            error_message=None,
        )
    )
    session.commit()
    return bool(result.rowcount)


# A job is "running" only while a process holds its execution lock. One left running by a
# process that no longer exists would block the same request for ever (an on-demand facility load
# is unique while active).
ABANDONED_AFTER = timedelta(minutes=10)


def reclaim_abandoned_sync_jobs(session: Session, now: datetime | None = None) -> int:
    """Mark as failed the jobs whose process stopped while they were running. PostgreSQL only.

    Only job kinds whose executor holds ``sync_job_execution_lock`` for the whole run are
    considered: on-demand facility loads and the scheduled refresh. If the lock can be taken,
    nothing is executing the job. Its transaction died with its process, so nothing was stored.
    """
    if session.get_bind().dialect.name != "postgresql":
        return 0
    moment = now or datetime.now(UTC)
    candidates = session.scalars(
        select(SyncJob.id).where(
            SyncJob.status == JobStatus.RUNNING.value,
            SyncJob.started_at.is_not(None),
            SyncJob.started_at < moment - ABANDONED_AFTER,
            or_(SyncJob.job_type == "aggregate_facilities", SyncJob.idempotency_key.like("scheduled:%")),
        )
    ).all()
    session.commit()
    reclaimed = 0
    for job_id in candidates:
        with sync_job_execution_lock(session, job_id) as acquired:
            if not acquired:
                continue
            result = session.execute(
                update(SyncJob)
                .where(SyncJob.id == job_id, SyncJob.status == JobStatus.RUNNING.value)
                .values(
                    status=JobStatus.FAILED.value,
                    error_code="interrupted",
                    error_message=(
                        "The process running this job stopped before it finished. Nothing was stored; "
                        "the job can be requested again."
                    ),
                    finished_at=moment,
                )
            )
            session.commit()
            reclaimed += result.rowcount or 0
    return reclaimed


def record_sync_internal_failure(session: Session, job_id: UUID) -> None:
    """Make an unexpected worker failure visible without storing exception details."""
    session.execute(
        update(SyncJob)
        .where(SyncJob.id == job_id, SyncJob.status == JobStatus.RUNNING.value)
        .values(
            status=JobStatus.FAILED.value,
            error_code="internal_sync_error",
            error_message="The synchronisation worker failed unexpectedly and will retry.",
            finished_at=datetime.now(UTC),
        )
    )
    session.commit()


def execute_sync_job(
    session: Session,
    job_id: UUID,
    client: Dhis2HttpClient | None = None,
    *,
    already_claimed: bool = False,
) -> SyncJob:
    job = session.get(SyncJob, job_id)
    if job is None:
        raise ValueError("Sync job not found.")
    session.refresh(job)
    # The gates are rechecked here, not only where the job was created: a queued job may be
    # executed by a worker long after the operator switched DHIS2 or synchronisation off.
    # An injected client is a test double and carries its own expectations.
    if client is None:
        try:
            ensure_extraction_enabled(get_settings())
        except Dhis2Disabled as exc:
            job.status = JobStatus.FAILED.value
            job.error_code = exc.code
            job.error_message = exc.message
            _finish(job)
            session.flush()
            return job
    if job.cancelled or job.status == JobStatus.CANCELLED.value:
        job.status = JobStatus.CANCELLED.value
        _finish(job)
        session.flush()
        return job
    if already_claimed:
        if job.status != JobStatus.RUNNING.value:
            return job
    else:
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
    if job.initiated_by_user_id is not None:
        actor = session.get(User, job.initiated_by_user_id)
        programme = session.get(Programme, job.programme_id) if job.programme_id else None
        try:
            if actor is None or not actor.is_active or programme is None:
                raise AuthorizationError("forbidden", "Sync initiator is no longer authorised.")
            require_action(
                session,
                actor,
                ActionPermission.VIEW if job.job_type == "aggregate_facilities" else ActionPermission.MANAGE_SYNC,
            )
            require_org_unit_access(session, actor, org_unit.id, period=job.period_from)
            require_programme_access(session, actor, programme.code)
        except AuthorizationError:
            job.status = JobStatus.FAILED.value
            job.error_code = "initiator_permissions_changed"
            job.error_message = "Current permissions no longer authorise this sync job."
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
        if job.job_type == FACILITY_AGGREGATE_JOB_TYPE:
            return _run_facility_aggregate(session, job, org_unit, client)
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


FACILITY_AGGREGATE_JOB_TYPE = "aggregate_facilities"


def _facility_uids(session: Session, target: OrgUnit, as_of: date | None = None) -> list[str]:
    """Mapped facilities only inside the authorised requested subtree."""
    period = as_of.strftime("%Y%m") if as_of else None
    facilities = [
        unit
        for unit in descendants(session, target, include_self=True, period=period)
        if unit.level_type == OrgUnitLevel.FACILITY.value
    ]
    if not facilities:
        return []
    query = select(OrgUnitMapping).where(
        OrgUnitMapping.org_unit_id.in_([unit.id for unit in facilities]),
        OrgUnitMapping.source_system == MappingSourceSystem.DHIS2.value,
    )
    if as_of is not None:
        query = query.where(
            or_(OrgUnitMapping.valid_from.is_(None), OrgUnitMapping.valid_from <= as_of),
            or_(OrgUnitMapping.valid_to.is_(None), OrgUnitMapping.valid_to >= as_of),
        )
    rows = session.scalars(query).all()
    by_unit = {}
    by_uid = {}
    for row in rows:
        if row.org_unit_id in by_unit or row.external_uid in by_uid:
            raise OrgScopeError("mapping_ambiguous", "Facility mappings overlap for the requested date.")
        by_unit[row.org_unit_id] = row.external_uid
        by_uid[row.external_uid] = row.org_unit_id
    return sorted({row.external_uid for row in rows})


def _run_facility_aggregate(
    session: Session, job: SyncJob, org_unit: OrgUnit, client: Dhis2HttpClient | None
) -> SyncJob:
    """Every month from ``period_from`` to ``period_to`` for one district's facilities."""
    if org_unit.level_type not in {
        OrgUnitLevel.DISTRICT.value,
        OrgUnitLevel.CITY.value,
        OrgUnitLevel.SUB_COUNTY.value,
        OrgUnitLevel.FACILITY.value,
    }:
        job.status = JobStatus.FAILED.value
        job.error_code = "invalid_geography"
        job.error_message = "Facility loads require a district, city, sub-county or facility subtree."
        _finish(job)
        session.flush()
        return job
    months: list[str] = []
    year, month = int(job.period_from[:4]), int(job.period_from[4:6])
    while f"{year}{month:02d}" <= job.period_to:
        months.append(f"{year}{month:02d}")
        month += 1
        if month > 12:
            month, year = 1, year + 1
    try:
        uids = _facility_uids(session, org_unit, parse_period(months[0]).start)
    except OrgScopeError as exc:
        job.status = JobStatus.FAILED.value
        job.error_code, job.error_message = exc.code, exc.message
        _finish(job)
        session.flush()
        return job
    if not uids:
        job.status = JobStatus.FAILED.value
        job.error_code = "mapping_missing"
        job.error_message = "No in-force DHIS2 facility mappings exist in the authorised subtree."
        _finish(job)
        session.flush()
        return job
    return _run_aggregate(session, job, org_unit, months, client, org_unit_uids=uids)


def _mapping_semantics(mapping: SourceMapping) -> str:
    return str(mapping.aggregation_semantics or "SUM").strip().upper()


def _component_checksum(observations: list[AggregateObservation]) -> str:
    evidence = [
        {
            "period": item.period,
            "checksum": item.payload_checksum,
            "value": item.value,
            "absence": item.absence_reason,
            "invalid": item.value_invalid,
        }
        for item in sorted(observations, key=lambda row: row.period)
    ]
    payload = json.dumps(evidence, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _normalise_period_observations(
    observations: list[AggregateObservation],
    translation: PeriodTranslation,
    semantics: str,
) -> list[AggregateObservation]:
    """Return one observation per item/geography/category under the HPIP period key.

    Native DHIS2 labels such as ``2026July`` are never persisted as analytical periods. Monthly
    routes are fail-closed: AVERAGE needs every constituent month; LAST needs the final calendar
    month. Missing components produce an unavailable value rather than a partial calculation.
    """
    unexpected = [
        item.period for item in observations if not covering_internal_period(item.period, translation.internal_key)
    ]
    if unexpected:
        raise Dhis2ValidationError(f"DHIS2 returned {len(unexpected)} rows outside {translation.internal_key}.")
    if not translation.is_monthly_route:
        return [
            AggregateObservation(
                org_unit_uid=item.org_unit_uid,
                period=translation.internal_key,
                item_uid=item.item_uid,
                value=item.value,
                category_option_combo_uid=item.category_option_combo_uid,
                source_freshness_at=item.source_freshness_at,
                absence_reason=item.absence_reason,
                payload_checksum=item.payload_checksum,
                value_invalid=item.value_invalid,
                source_periods=(item.period,),
            )
            for item in observations
        ]

    grouped: dict[tuple[str, str, str], list[AggregateObservation]] = {}
    for item in observations:
        identity = (
            item.item_uid,
            item.org_unit_uid,
            item.category_option_combo_uid or "",
        )
        grouped.setdefault(identity, []).append(item)
    expected = tuple(translation.dhis2_periods)
    results: list[AggregateObservation] = []
    for (item_uid, org_uid, coc), rows in grouped.items():
        by_period = {row.period: row for row in rows}
        selected: list[AggregateObservation]
        value: float | None
        invalid = False
        absence: str | None = None
        if semantics in {"SUM", "COUNT", "AVERAGE"}:
            selected = [by_period[period] for period in expected if period in by_period]
            complete = len(selected) == len(expected)
            invalid = any(row.value_invalid for row in selected)
            numeric = [row.value for row in selected if row.value is not None]
            if complete and not invalid and len(numeric) == len(expected):
                value = sum(numeric) / len(numeric) if semantics == "AVERAGE" else sum(numeric)
            else:
                value = None
                absence = AbsenceReason.INVALID_VALUE.value if invalid else AbsenceReason.NO_SOURCE_ROW.value
        elif semantics == "LAST":
            selected = list(rows)
            last = by_period.get(expected[-1])
            invalid = bool(last and last.value_invalid)
            if last is not None and last.value is not None and not invalid:
                value = last.value
            else:
                value = None
                absence = AbsenceReason.INVALID_VALUE.value if invalid else AbsenceReason.NO_SOURCE_ROW.value
        else:  # guarded by mapping validation; retained as a fail-closed invariant
            raise Dhis2ValidationError(f"Monthly retrieval cannot apply aggregation semantics {semantics!r}.")
        freshness = [row.source_freshness_at for row in selected if row.source_freshness_at]
        results.append(
            AggregateObservation(
                org_unit_uid=org_uid,
                period=translation.internal_key,
                item_uid=item_uid,
                value=value,
                category_option_combo_uid=coc or None,
                source_freshness_at=min(freshness) if freshness else None,
                absence_reason=absence,
                payload_checksum=_component_checksum(selected),
                value_invalid=invalid,
                source_periods=tuple(row.period for row in sorted(selected, key=lambda row: row.period)),
            )
        )
    return results


def _fetch_aggregate_periods(
    adapter: AggregateAnalyticsAdapter,
    mappings: list[SourceMapping],
    org_unit_uids: list[str],
    periods: list[str],
) -> tuple[list[AggregateObservation], int]:
    """Fetch mappings in compatible groups and return internal-period observations."""
    grouped: dict[tuple[str, bool], list[SourceMapping]] = {}
    for mapping in mappings:
        grouped.setdefault((_mapping_semantics(mapping), bool(mapping.category_option_combo_uid)), []).append(mapping)

    normalised: list[AggregateObservation] = []
    upstream_received = 0
    for internal_period in dict.fromkeys(periods):
        for (semantics, category_detail), rows in grouped.items():
            translation = translate_period(
                internal_period,
                aggregation_semantics=semantics,
            )
            dx_uids = [
                (f"{row.dhis2_item_uid}.{row.category_option_combo_uid}" if category_detail else row.dhis2_item_uid)
                for row in rows
                if row.dhis2_item_uid
            ]
            fetched = adapter.fetch(
                dx_uids=dx_uids,
                org_unit_uids=org_unit_uids,
                periods=list(translation.dhis2_periods),
                # Category mappings use an exact data-element operand (DE.COC). Requesting the
                # unrestricted `co` dimension would retrieve every visible category row and then
                # discard most of them, and could hide a permission/configuration error.
                include_category_option_combos=False,
            )
            if not fetched.complete:
                raise Dhis2ValidationError(
                    f"Only {fetched.chunks_succeeded} of {fetched.chunks_requested} analytics "
                    "chunks completed, so the retrieval is partial."
                )
            upstream_received += len(fetched.observations)
            if category_detail:
                allowed = {
                    (row.dhis2_item_uid, row.category_option_combo_uid or "") for row in rows if row.dhis2_item_uid
                }
                observations = [
                    item
                    for item in fetched.observations
                    if (item.item_uid, item.category_option_combo_uid or "") in allowed
                ]
            else:
                allowed_uids = {row.dhis2_item_uid for row in rows if row.dhis2_item_uid}
                observations = [item for item in fetched.observations if item.item_uid in allowed_uids]
            normalised.extend(_normalise_period_observations(observations, translation, semantics))
    return normalised, upstream_received


def _run_aggregate(
    session: Session,
    job: SyncJob,
    org_unit: OrgUnit,
    periods: list[str],
    client: Dhis2HttpClient | None,
    org_unit_uids: list[str] | None = None,
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
        ou_uids = org_unit_uids if org_unit_uids is not None else _mapped_org_unit_uids(session, org_unit, as_of)
        summed = [row for row in mappings if row.item_kind != "indicator"]
        direct = [row for row in mappings if row.item_kind == "indicator"]
        observations, upstream_received = (
            _fetch_aggregate_periods(adapter, summed, ou_uids, periods) if summed else ([], 0)
        )
        if direct:
            # A DHIS2 indicator is a ratio: it cannot be summed from districts, so the country and
            # region units in scope are requested directly as well (D-065).
            extra = [] if org_unit_uids is not None else _aggregate_level_uids(session, org_unit, as_of)
            direct_observations, direct_received = _fetch_aggregate_periods(adapter, direct, ou_uids + extra, periods)
            observations = observations + direct_observations
            upstream_received += direct_received
        requested_uids = set(ou_uids + (extra if direct else []))
        requested_units = list(
            session.scalars(
                select(OrgUnitMapping.org_unit_id).where(
                    OrgUnitMapping.source_system == MappingSourceSystem.DHIS2.value,
                    OrgUnitMapping.external_uid.in_(requested_uids),
                    or_(OrgUnitMapping.valid_from.is_(None), OrgUnitMapping.valid_from <= as_of),
                    or_(OrgUnitMapping.valid_to.is_(None), OrgUnitMapping.valid_to >= as_of),
                )
            ).all()
        )
        # Record exact request dimensions: native percentages include parent units,
        # summable counts do not. A union must not certify unrequested parent counts.
        uid_to_units = {}
        for uid, unit_id in session.execute(
            select(OrgUnitMapping.external_uid, OrgUnitMapping.org_unit_id).where(
                OrgUnitMapping.source_system == MappingSourceSystem.DHIS2.value,
                OrgUnitMapping.external_uid.in_(requested_uids),
                or_(OrgUnitMapping.valid_from.is_(None), OrgUnitMapping.valid_from <= as_of),
                or_(OrgUnitMapping.valid_to.is_(None), OrgUnitMapping.valid_to >= as_of),
            )
        ):
            uid_to_units.setdefault(uid, set()).add(unit_id)
        scopes = [
            {
                "source_key": mapping.internal_source_key,
                "item_uid": mapping.dhis2_item_uid,
                "category_option_combo_uid": mapping.category_option_combo_uid,
                "org_unit_ids": sorted(
                    {
                        unit_id
                        for uid in (ou_uids + (extra if mapping.item_kind == "indicator" else []))
                        for unit_id in uid_to_units.get(uid, set())
                    },
                    key=str,
                ),
                "periods": list(periods),
            }
            for mapping in mappings
            if mapping.dhis2_item_uid
        ]
        job.coverage_manifest = {
            "version": 1,
            "complete": False,
            "periods": list(periods),
            "source_keys": sorted({row.internal_source_key for row in mappings}),
            "org_unit_ids": sorted({str(unit_id) for unit_id in requested_units}),
            "mapping_ids": sorted(str(row.id) for row in mappings),
            "requests": [
                {**scope, "org_unit_ids": [str(unit_id) for unit_id in scope["org_unit_ids"]]} for scope in scopes
            ],
        }
        by_uid = {
            (row.dhis2_item_uid, row.category_option_combo_uid or ""): row for row in mappings if row.dhis2_item_uid
        }
        seen_row_ids = set()
        counts = persist_aggregate_observations(
            session, job, observations, by_uid, datetime.now(UTC), seen_row_ids=seen_row_ids
        )
        job.received_count = upstream_received
        job.retry_count = http.last_retry_count
        if _cancelled(session, job.id):
            job.status = JobStatus.CANCELLED.value
        elif counts["rejected"]:
            job.status = JobStatus.PARTIALLY_SUCCEEDED.value
        else:
            job.status = JobStatus.SUCCEEDED.value
            job.coverage_manifest = {**job.coverage_manifest, "complete": True}
            from app.services.sync_reconciliation import reconcile_aggregate_withdrawals

            reconcile_aggregate_withdrawals(session, job, seen_row_ids=seen_row_ids, scopes=scopes)
        job.source_freshness_at = _oldest_freshness(observations)
    except OrgScopeError as exc:
        job.status = JobStatus.FAILED.value
        job.error_code = exc.code
        job.error_message = exc.message
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
    program_uids = sorted({row.program_uid for row in mappings if row.program_uid})
    if not program_uids:
        return _fail_mapping(session, job)
    occurred_after, occurred_before = _period_bounds(periods)
    if job.window_end is not None and occurred_before is not None:
        # An explicit, validated window end extends retrieval through the extraction date.
        occurred_before = max(job.window_end.isoformat(), occurred_before)
    if occurred_before:
        occurred_before = min(occurred_before, datetime.now(UTC).date().isoformat())
    job.window_start = date.fromisoformat(occurred_after) if occurred_after else None
    job.window_end = date.fromisoformat(occurred_before) if occurred_before else None
    owned = client is None
    http = client or Dhis2HttpClient(cancelled=lambda: _cancelled(session, job.id))
    try:
        adapter = TrackerEventsAdapter(http)
        ou_uids = _mapped_org_unit_uids(session, org_unit, as_of)
        observations = []
        page_limit_reached = False
        for program_uid in program_uids:
            result = adapter.fetch_events_result(
                program_uid=program_uid,
                org_unit_uids=ou_uids,
                # D-068 retrieves descendants of each non-overlapping peer. Keep
                # the actual request aligned with withdrawal-certification scope.
                ou_mode="DESCENDANTS",
                occurred_after=occurred_after,
                occurred_before=occurred_before,
                allowed_data_element_uids={
                    row.source_data_element_uid
                    for row in mappings
                    if row.program_uid == program_uid
                    and row.source_data_element_uid
                    and row.source_data_element_uid != EVENT_DATE_SOURCE
                },
            )
            observations.extend(result.observations)
            page_limit_reached = page_limit_reached or result.page_limit_reached
        job.coverage_manifest = {
            "version": 1,
            "complete": False,
            "program_uids": program_uids,
            "ou_mode": "DESCENDANTS",
            "mapping_ids": sorted(str(row.id) for row in mappings),
            "org_unit_uids": sorted(ou_uids),
            "periods": list(periods),
        }
        result = TrackerFetchResult(observations=observations, page_limit_reached=page_limit_reached, pages_fetched=0)
        seen_row_ids = set()
        counts = persist_event_observations(
            session, job, result.observations, mappings, datetime.now(UTC), seen_row_ids=seen_row_ids
        )
        job.coverage_manifest = {**job.coverage_manifest, "missing_death_dates": counts["missing_death_dates"]}
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
            job.coverage_manifest = {**job.coverage_manifest, "complete": True}
            from app.services.sync_reconciliation import reconcile_event_withdrawals

            roots = set(
                session.scalars(
                    select(OrgUnitMapping.org_unit_id).where(
                        OrgUnitMapping.source_system == MappingSourceSystem.DHIS2.value,
                        OrgUnitMapping.external_uid.in_(ou_uids),
                        or_(OrgUnitMapping.valid_from.is_(None), OrgUnitMapping.valid_from <= as_of),
                        or_(OrgUnitMapping.valid_to.is_(None), OrgUnitMapping.valid_to >= as_of),
                    )
                ).all()
            )
            job.coverage_manifest = {**job.coverage_manifest, "org_unit_ids": sorted(str(root) for root in roots)}
            reconcile_event_withdrawals(
                session, job, seen_row_ids=seen_row_ids, root_ids=roots, program_uids=program_uids
            )
    except OrgScopeError as exc:
        job.status = JobStatus.FAILED.value
        job.error_code = exc.code
        job.error_message = exc.message
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
    program_uid = resolve_programme_uid(session, job.programme_id, job.mapping_version or "v1", as_of=as_of)
    if not program_uid:
        return _fail_mapping(session, job)
    owned = client is None
    http = client or Dhis2HttpClient(cancelled=lambda: _cancelled(session, job.id))
    try:
        adapter = EventAnalyticsAdapter(http)
        ou_uids = _mapped_org_unit_uids(session, org_unit, as_of)
        observations = adapter.query_events(
            program_uid=program_uid,
            org_unit_uids=ou_uids,
            periods=_event_native_periods(periods),
        )
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
    except OrgScopeError as exc:
        job.status = JobStatus.FAILED.value
        job.error_code = exc.code
        job.error_message = exc.message
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
            source_periods=item.source_periods,
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
    by_uid = {(row.dhis2_item_uid, row.category_option_combo_uid or ""): row for row in mappings if row.dhis2_item_uid}
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
    program_uid = resolve_programme_uid(session, job.programme_id, job.mapping_version or "v1", as_of=as_of)
    if not program_uid:
        return _fail_mapping(session, job)
    owned = client is None
    http = client or Dhis2HttpClient(cancelled=lambda: _cancelled(session, job.id))
    try:
        adapter = EventAnalyticsAdapter(http)
        ou_uids = _mapped_org_unit_uids(session, org_unit, as_of)
        observations: list[EventAggregateObservation] = []
        for internal_period in dict.fromkeys(periods):
            translation = translate_period(internal_period, aggregation_semantics="COUNT")
            fetched = adapter.aggregate(
                program_uid=program_uid,
                org_unit_uids=ou_uids,
                periods=list(translation.dhis2_periods),
            )
            observations.extend(_normalise_event_aggregate_periods(fetched, internal_period))
        persist_event_aggregate_observations(session, job, observations, datetime.now(UTC))
        job.retry_count = http.last_retry_count
        job.status = JobStatus.SUCCEEDED.value if job.rejected_count == 0 else JobStatus.PARTIALLY_SUCCEEDED.value
        job.source_freshness_at = _oldest_freshness(observations)
    except OrgScopeError as exc:
        job.status = JobStatus.FAILED.value
        job.error_code = exc.code
        job.error_message = exc.message
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
    return bool(session.scalar(select(SyncJob.cancelled).where(SyncJob.id == job_id)))


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
    # `status` describes the attempt. Whether the *programme* is actually usable is a separate
    # question: a set that maps one of forty-eight source keys can sync perfectly and still leave
    # almost every indicator unresolvable. Recording coverage alongside the attempt keeps both
    # facts, so nothing downstream can infer programme readiness from a successful job alone.
    if job.programme_id is not None:
        report = evaluate_coverage(
            session,
            programme_id=job.programme_id,
            mapping_version=job.mapping_version or "v1",
        )
        coverage = report.as_dict()
        # Name the keys that were not extracted, so an operator can see exactly which indicators
        # are unavailable and why, rather than inferring it from a count.
        coverage["unresolved_source_keys"] = sorted(report.unresolved)
        detail["mapping_coverage"] = coverage
        detail["programme_ready"] = bool(report.complete)
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

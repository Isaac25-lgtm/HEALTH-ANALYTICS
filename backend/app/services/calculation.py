from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import Numeric, String, cast, func, or_, select
from sqlalchemy.orm import Session, defer
from sqlalchemy.orm.util import identity_key

from app.config import get_settings
from app.domain.enums import (
    AGGREGATION_CLASS_RANK,
    AbsenceReason,
    AggregationClass,
    EventCoverageStatus,
    FormulaKind,
    JobStatus,
    Over100Behaviour,
    PerformanceStatus,
    SourceAggregationPolicy,
    UnavailableReason,
    aggregation_class,
)
from app.domain.formula_spec import FormulaValidationError, validate_classification_spec, validate_formula_spec
from app.domain.indicator_catalog import INDICATOR_BY_CODE
from app.domain.periods import parse_period
from app.models import (
    AnalyticsRevision,
    CalculatedValue,
    CalculationRun,
    CalculationRunMemo,
    EventFieldMapping,
    FacilityPopulationEntry,
    Indicator,
    IndicatorVersion,
    OrgUnit,
    PeriodPopulationRule,
    PopulationSourceAlias,
    PopulationValue,
    PopulationVersion,
    Programme,
    RawAggregateValue,
    RawEventSnapshot,
    SourceMapping,
    SyncJob,
    User,
)
from app.services.classification import classify, display_value
from app.services.event_coverage import evaluate_event_coverage
from app.services.geography import descendants, escape_like, top_units_of_class, unit_in_period
from app.services.mpdsr import (
    chronology_valid_notification,
    chronology_valid_review,
    is_completed,
    notification_timely,
    review_timely,
)
from app.services.mpdsr_events import mpdsr_scope, scoped_mpdsr_events
from app.services.population import TargetDenominator, resolve_target_denominator
from app.version import SOFTWARE_VERSION

ABSENT_REASONS = {
    AbsenceReason.NO_SOURCE_ROW.value,
    AbsenceReason.UNAVAILABLE.value,
    AbsenceReason.MAPPING_FAILURE.value,
    AbsenceReason.INVALID_VALUE.value,
}

# Follow-up windows already fixed by the MPDSR timeliness rules (same/next calendar day;
# review within 0–7 days). A verified zero for a timeliness numerator needs source
# coverage through the cohort end plus this window.
NOTIFICATION_FOLLOW_UP_DAYS = 1
REVIEW_FOLLOW_UP_DAYS = 7

# Scope failures that indicate a data-quality or reconciliation problem rather than
# a simply absent component.
QUALITY_SCOPE_REASONS = {
    UnavailableReason.INCOMPATIBLE_SCOPE.value,
    UnavailableReason.MIXED_LEVELS.value,
    UnavailableReason.MIXED_MAPPING_VERSIONS.value,
    UnavailableReason.AMBIGUOUS_SOURCE.value,
    UnavailableReason.INCOMPLETE_CHILDREN.value,
}


@dataclass
class SourceResolution:
    value: float | None
    status: str
    policy: str
    level: str | None
    unit_ids: list[UUID] = field(default_factory=list)
    row_ids: list[UUID] = field(default_factory=list)
    mapping_versions: list[str] = field(default_factory=list)
    reason: str | None = None


@dataclass
class ScopeResolution:
    """One common geography/aggregation scope shared by every aggregate component."""

    status: str
    policy: str | None
    level: str | None
    values: dict[str, float] = field(default_factory=dict)
    row_ids: list[UUID] = field(default_factory=list)
    unit_ids: list[UUID] = field(default_factory=list)
    mapping_versions: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    reason: str | None = None
    reason_code: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"


@dataclass
class Measure:
    numerator: float | None
    denominator: float | None
    raw_value: float | None
    status: str
    performance_status: str | None
    quality_status: str | None
    blue_reason: str | None = None
    notes: list[str] = field(default_factory=list)
    population_year: int | None = None
    population_version_id: UUID | None = None
    facility_population_entry_id: UUID | None = None
    missing_components: list[str] = field(default_factory=list)
    aggregation_policy: str | None = None
    aggregation_level: str | None = None
    source_row_ids: list[str] = field(default_factory=list)
    mapping_version: str | None = None
    reason_code: str | None = None
    event_snapshot_ids: list[str] = field(default_factory=list)
    event_coverage: dict | None = None
    denominator_provenance: dict | None = None


@dataclass
class EventCountResult:
    count: int | None
    event_ids: list[str]
    coverage: dict
    reason: str | None = None


def current_raw(
    session: Session,
    org_unit_id: UUID,
    period: str,
    source_key: str,
    programme_id: UUID | None = None,
) -> RawAggregateValue | None:
    rows = _current_raw_rows(session, org_unit_id, period, source_key, programme_id)
    return rows[0] if len(rows) == 1 else None


BATCH_INFO_KEY = "calc_batch"


def _batch(session: Session) -> dict | None:
    return session.info.get(BATCH_INFO_KEY)


class _CalculationBatch(dict):
    """A calculation batch whose source rows and events are read on first use.

    A view whose runs are all verified at the current analytics revision never recalculates, so
    it must not pay for loading every source row of the subtree.
    """

    _LAZY = ("raw_index", "raw_row_ids", "events")

    def __init__(self, loader, values: dict) -> None:
        super().__init__(values)
        self._loader = loader

    def _pending(self, key) -> bool:
        return self._loader is not None and key in self._LAZY

    def __missing__(self, key):
        if not self._pending(key):
            raise KeyError(key)
        loader, self._loader = self._loader, None
        self.update(loader())
        return dict.__getitem__(self, key)

    def __contains__(self, key) -> bool:
        return dict.__contains__(self, key) or self._pending(key)

    def get(self, key, default=None):
        if self._pending(key):
            return self[key]
        return dict.get(self, key, default)


def prepare_calculation_batch(
    session: Session,
    *,
    org_unit: OrgUnit,
    periods: list[str],
    programme_codes: list[str] | None = None,
) -> dict:
    # Financial years, quarters, calendar years and custom ranges are built from stored months
    # before anything is read, so every period resolves from the same monthly source. A
    # concurrent request may build the same period first; that is harmless, so the savepoint is
    # rolled back and its rows are simply read.
    from sqlalchemy.exc import IntegrityError

    from app.services.period_rollup import ensure_period_rollups

    try:
        with session.begin_nested():
            ensure_period_rollups(session, periods)
    except IntegrityError:
        pass
    # Optimistic guard for prepared products: never stamp a calculation made from an
    # older batch with a newer concurrent source revision.
    # Read for every batch: an earlier batch of the same session may predate a source change.
    revisions = dict(
        session.execute(
            select(AnalyticsRevision.key, AnalyticsRevision.revision).where(
                AnalyticsRevision.key.in_(["global", "config"])
            )
        ).all()
    )
    input_revision = revisions.get("global")
    session.info.setdefault("product_input_revision", input_revision)
    units = descendants(session, org_unit, include_self=True, active_only=False)
    # Rows are selected by subtree path: an 11,000-item ID list is far slower to send and plan.
    subtree_query = select(OrgUnit.id).where(
        or_(
            OrgUnit.id == org_unit.id,
            OrgUnit.path.like(escape_like(org_unit.path.rstrip("/") + "/") + "%", escape="\\"),
        ),
    )
    # Formulas read source rows of their own programme only, so a module's batch loads that
    # programme's rows. Provenance JSON is not needed to calculate; lineage fetches the mapping IDs
    # it needs in one light query (see _batch_mapping_ids).
    raw_query = (
        select(RawAggregateValue)
        .options(defer(RawAggregateValue.provenance))
        .where(
            RawAggregateValue.org_unit_id.in_(subtree_query),
            RawAggregateValue.period.in_(periods),
            RawAggregateValue.is_current.is_(True),
        )
    )
    if programme_codes:
        raw_query = raw_query.where(
            RawAggregateValue.programme_id.in_(select(Programme.id).where(Programme.code.in_(programme_codes)))
        )

    # An exact per-unit, per-period fingerprint of the same rows, computed by the database. It
    # is what lets a run be re-verified after an unrelated change without reading its rows.
    row_text = func.concat_ws(
        "|",
        cast(RawAggregateValue.id, String),
        func.coalesce(RawAggregateValue.checksum, "~"),
        func.coalesce(cast(RawAggregateValue.value, String), "~"),
        func.coalesce(cast(RawAggregateValue.programme_id, String), "~"),
        cast(RawAggregateValue.value_invalid, String),
        func.coalesce(RawAggregateValue.absence_reason, "~"),
        RawAggregateValue.internal_source_key,
        func.coalesce(RawAggregateValue.mapping_version, "~"),
        func.coalesce(RawAggregateValue.dhis2_item_uid, "~"),
        func.coalesce(RawAggregateValue.category_option_combo_uid, "~"),
        func.coalesce(cast(RawAggregateValue.extracted_at, String), "~"),
        func.coalesce(cast(RawAggregateValue.source_freshness_at, String), "~"),
    )
    digest_query = (
        select(
            RawAggregateValue.org_unit_id,
            RawAggregateValue.period,
            func.count(RawAggregateValue.id),
            func.sum(cast(func.hashtextextended(row_text, 0), Numeric)),
        )
        .where(raw_query.whereclause)
        .group_by(RawAggregateValue.org_unit_id, RawAggregateValue.period)
    )

    def load_sources() -> dict:
        # Fingerprints first: a row committed after them can only make a stored fingerprint
        # older than the rows a run read, which forces a later check to fail, never to pass.
        _source_digests(session, batch)
        if not programme_codes or "MPDSR" in programme_codes:
            _event_state(session, batch)
        raw_rows = list(session.scalars(raw_query).all())
        # Routine modules must not deserialize the national sensitive event cache.
        events = (
            list(
                session.scalars(
                    select(RawEventSnapshot).where(
                        RawEventSnapshot.org_unit_id.in_(subtree_query),
                        RawEventSnapshot.is_current.is_(True),
                        RawEventSnapshot.source_connector == "tracker",
                        RawEventSnapshot.extracted_at
                        > datetime.now(UTC) - timedelta(hours=get_settings().mpdsr_event_retention_hours),
                    )
                ).all()
            )
            if not programme_codes or "MPDSR" in programme_codes
            else []
        )
        raw_index: dict[tuple, list[RawAggregateValue]] = {}
        for row in raw_rows:
            raw_index.setdefault((row.org_unit_id, row.period, row.internal_source_key), []).append(row)
        return {"raw_index": raw_index, "raw_row_ids": [row.id for row in raw_rows], "events": events}

    loaded_versions = list(session.scalars(select(IndicatorVersion)).all())
    decisions_by_period = {
        key: resolve_indicator_versions_for_period(session, key, loaded=loaded_versions) for key in periods
    }
    values = {
        "input_revision": input_revision,
        "config_revision": revisions.get("config"),
        "digest_query": digest_query,
        "units": units,
        "unit_by_id": {unit.id: unit for unit in units},
        "version_decisions_by_period": decisions_by_period,
        "indicators": {row.id: row for row in session.scalars(select(Indicator)).all()},
        "programmes": {row.id: row for row in session.scalars(select(Programme)).all()},
        "versions_by_period": {
            key: [item.version for item in decisions.values() if item.version is not None]
            for key, decisions in decisions_by_period.items()
        },
        "query_batches": 4,
    }
    batch = _CalculationBatch(load_sources, values)
    session.info[BATCH_INFO_KEY] = batch
    return batch


# Run reuse. Inside a dashboard batch, a run whose inputs are identical to an earlier successful
# run is returned instead of recalculated: same software, unit, descendant hierarchy, period,
# programme and indicator set, selected formula versions, current source rows (identity, checksum
# and value), and reference tables (content-hashed, not timestamped). Event-based formulas also
# depend on the retained events, the Tracker synchronisations and the clock; their fingerprint
# carries all three (see _event_state), so they are reused only while none of them has changed.
RUN_REUSE_PREFIX = "inputs-v2:"
# Runs returned by reuse in this session; their quality flags were scanned when first calculated.
REUSED_RUNS_KEY = "reused_calculation_runs"
_REFERENCE_MODELS = (
    Indicator,
    IndicatorVersion,
    SourceMapping,
    EventFieldMapping,
    PeriodPopulationRule,
    PopulationVersion,
    PopulationValue,
    PopulationSourceAlias,
    FacilityPopulationEntry,
)
_REFERENCE_SKIP_COLUMNS = {"created_at", "updated_at"}


def _reference_state(session: Session, batch: dict) -> str:
    cached = batch.get("reference_state")
    if cached is not None:
        return cached
    digest = hashlib.sha256()
    for model in _REFERENCE_MODELS:
        columns = [column for column in model.__table__.columns if column.name not in _REFERENCE_SKIP_COLUMNS]
        digest.update(model.__tablename__.encode())
        rows = session.execute(select(*columns)).all()
        for row in sorted(repr(tuple(row)) for row in rows):
            digest.update(row.encode())
    batch["reference_state"] = digest.hexdigest()
    return batch["reference_state"]


def _request_uses_events(
    batch: dict,
    versions: list[IndicatorVersion],
    programme_codes: list[str] | None,
    indicator_codes: list[str] | None,
) -> bool:
    indicators = batch.get("indicators") or {}
    programmes = batch.get("programmes") or {}
    for version in versions:
        indicator = indicators.get(version.indicator_id)
        programme = programmes.get(indicator.programme_id) if indicator is not None else None
        if indicator is None or (programme is not None and programme_codes and programme.code not in programme_codes):
            continue
        if indicator_codes and indicator.code not in indicator_codes:
            continue
        spec = version.formula_spec or {}
        if any(
            isinstance(part, dict) and part.get("mode") == "event_count"
            for part in (spec.get("numerator"), spec.get("denominator"))
        ):
            return True
    return False


def _event_state(session: Session, batch: dict) -> dict:
    """Everything an event-based result depends on besides its aggregate rows and reference tables.

    ``digest`` changes whenever a retained event or a Tracker synchronisation changes. ``valid_until``
    is the first moment at which the clock alone would change a result: the oldest retained event
    reaching the retention limit, a covering synchronisation reaching the freshness limit, or
    midnight. It is computed before any event is read for calculation, so an event that expires
    while a run is being calculated leaves that run already out of date, never wrongly reusable.
    """
    cached = batch.get("event_state")
    if cached is not None:
        return cached
    settings = get_settings()
    now = datetime.now(UTC)
    retention = timedelta(hours=settings.mpdsr_event_retention_hours)
    freshness = timedelta(hours=min(settings.dhis2_stale_hours, settings.mpdsr_event_retention_hours))
    retained = session.execute(
        select(
            func.count(RawEventSnapshot.id),
            func.min(RawEventSnapshot.extracted_at),
            func.max(RawEventSnapshot.updated_at),
            func.max(RawEventSnapshot.created_at),
        ).where(
            RawEventSnapshot.is_current.is_(True),
            RawEventSnapshot.source_connector == "tracker",
            RawEventSnapshot.extracted_at > now - retention,
        )
    ).one()
    jobs = session.execute(
        select(
            SyncJob.id,
            SyncJob.status,
            SyncJob.cancelled,
            SyncJob.finished_at,
            SyncJob.page_limit_reached,
            SyncJob.rejected_count,
            SyncJob.window_start,
            SyncJob.window_end,
            SyncJob.mapping_version,
            SyncJob.programme_id,
            SyncJob.org_unit_id,
            SyncJob.coverage_manifest,
        )
        .where(SyncJob.job_type == "tracker")
        .order_by(SyncJob.id)
    ).all()
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    cutoffs = [tomorrow]
    if retained[1] is not None:
        cutoffs.append(_utc(retained[1]) + retention)
    for job in jobs:
        finished = _utc(job.finished_at)
        if job.status == JobStatus.SUCCEEDED.value and finished is not None and now - finished <= freshness:
            cutoffs.append(finished + freshness)
    valid_until = min(cutoffs)
    digest = hashlib.sha256()
    for item in (
        settings.mpdsr_event_retention_hours,
        settings.dhis2_stale_hours,
        retained[0],
        _utc(retained[1]),
        _utc(retained[2]),
        _utc(retained[3]),
        valid_until.isoformat(),
    ):
        digest.update(repr(item).encode())
        digest.update(b"|")
    for job in jobs:
        digest.update(
            repr(
                (
                    str(job.id),
                    job.status,
                    job.cancelled,
                    _utc(job.finished_at),
                    job.page_limit_reached,
                    job.rejected_count,
                    job.window_start,
                    job.window_end,
                    job.mapping_version,
                    str(job.programme_id),
                    str(job.org_unit_id),
                    json.dumps(job.coverage_manifest, sort_keys=True, default=str),
                )
            ).encode()
        )
    state = {"digest": digest.hexdigest(), "valid_until": valid_until}
    batch["event_state"] = state
    return state


def _input_fingerprint(
    session: Session,
    *,
    org_unit: OrgUnit,
    period: str,
    programme_codes: list[str] | None,
    indicator_codes: list[str] | None,
    versions: list[IndicatorVersion],
    decisions: dict,
) -> str | None:
    batch = _batch(session)
    if batch is None or not programme_codes or period not in (batch.get("version_decisions_by_period") or {}):
        return None
    uses_events = _request_uses_events(batch, versions, programme_codes, indicator_codes)
    hierarchy = batch.setdefault("hierarchy_digest", {})
    hierarchy_key = (org_unit.id, period)
    if hierarchy_key not in hierarchy:
        units = descendants(session, org_unit, include_self=True, period=period)
        unit_digest = hashlib.sha256()
        for line in sorted(
            f"{unit.id}|{unit.path}|{unit.level_type}|{unit.active}|{unit.valid_from}|{unit.valid_to}" for unit in units
        ):
            unit_digest.update(line.encode())
        hierarchy[hierarchy_key] = ({unit.id for unit in units}, unit_digest.hexdigest())
    unit_ids, hierarchy_hash = hierarchy[hierarchy_key]
    digest = hashlib.sha256()
    material = [
        SOFTWARE_VERSION,
        str(org_unit.id),
        period,
        ",".join(sorted(programme_codes)),
        ",".join(sorted(indicator_codes or [])),
        get_settings().undated_formula_policy,
        _reference_state(session, batch),
    ]
    from app.services.prepared_dashboard import calculation_build_signature

    material.extend([calculation_build_signature(), str(get_settings().mpdsr_reporting_units_approved)])
    if uses_events:
        material.append("events:" + _event_state(session, batch)["digest"])
    material.append(hierarchy_hash)
    material.extend(
        sorted(
            f"{decision.indicator_id}|{decision.version.id if decision.version else '-'}|{decision.rule}"
            for decision in decisions.values()
        )
    )
    by_unit_period = batch.get("raw_by_unit_period")
    if by_unit_period is None:
        by_unit_period = {}
        for (unit_id, row_period, _key), group in batch["raw_index"].items():
            by_unit_period.setdefault((unit_id, row_period), []).extend(group)
        batch["raw_by_unit_period"] = by_unit_period
    del unit_ids  # the hierarchy digest covers every descendant; the rows are those the run reads
    rows = [
        row
        for unit_id in _read_units(session, org_unit, period)
        for row in by_unit_period.get((unit_id, period), [])
    ]
    material.extend(
        sorted(
            f"{row.id}|{row.checksum}|{row.value}|{row.programme_id}|{row.value_invalid}|{row.absence_reason}|"
            f"{row.internal_source_key}|{row.mapping_version}|{row.dhis2_item_uid}|{row.category_option_combo_uid}|"
            f"{row.extracted_at}|{row.source_freshness_at}"
            for row in rows
        )
    )
    for item in material:
        digest.update(str(item).encode())
        digest.update(b"\n")
    return RUN_REUSE_PREFIX + digest.hexdigest()


def _reusable_run(session: Session, org_unit: OrgUnit, period: str, fingerprint: str) -> CalculationRun | None:
    return session.scalar(
        select(CalculationRun)
        .where(
            CalculationRun.idempotency_key == fingerprint,
            CalculationRun.geography_org_unit_id == org_unit.id,
            CalculationRun.period == period,
            CalculationRun.status == JobStatus.SUCCEEDED.value,
        )
        .order_by(CalculationRun.finished_at.desc())
        .limit(1)
    )


def clear_calculation_batch(session: Session) -> None:
    session.info.pop(BATCH_INFO_KEY, None)
    session.info.pop(MEMO_PENDING_KEY, None)
    session.info.pop(MEMO_STATE_KEY, None)


# Verified-run memo. Every input of a non-event calculation lives in a table whose changes bump the
# global analytics revision (see app/db/analytics_revision.py), or is part of the request key below.
# A run stamped at revision R is therefore still exact while the revision equals R, and is returned
# with one lookup. The revision is the one read when this batch was prepared, before any source
# row was read, so a change committed while a run was being calculated always leaves the stamp
# behind the global revision and forces the full input fingerprint on the next request.
#
# A change elsewhere moves the revision without touching a given run: facility rows loaded for one
# district say nothing about another district or about a different period. A stamp that is behind
# the revision is therefore checked a second way before the run is given up: the configuration
# revision (every non-source table) must be unchanged, and an exact database-computed fingerprint
# of the source rows the run reads (its subtree, period and programme; plus the event state for an
# event-based run) must equal the one stored with it. PostgreSQL only; elsewhere the full input
# fingerprint decides, as before.
MEMO_PENDING_KEY = "calculation_run_memo_pending"
MEMO_STATE_KEY = "calculation_run_memo_state"
QUALITY_SCAN_REUSE = timedelta(hours=1)


def _memo_key(
    org_unit: OrgUnit, period: str, programme_codes: list[str] | None, indicator_codes: list[str] | None
) -> str | None:
    if not programme_codes:
        return None
    from app.services.prepared_dashboard import calculation_build_signature

    settings = get_settings()
    material = "\n".join(
        [
            SOFTWARE_VERSION,
            calculation_build_signature(),
            str(org_unit.id),
            period,
            ",".join(sorted(programme_codes)),
            ",".join(sorted(indicator_codes or [])),
            settings.undated_formula_policy,
            str(settings.mpdsr_reporting_units_approved),
            str(settings.mpdsr_event_retention_hours),
            str(settings.dhis2_stale_hours),
        ]
    )
    return hashlib.sha256(material.encode()).hexdigest()


def _source_digests(session: Session, batch: dict) -> dict | None:
    """``{(unit, period): (row count, fingerprint sum)}`` for the batch's source rows, or None."""
    if "source_digests" in batch:
        return batch["source_digests"]
    digests = None
    query = batch.get("digest_query")
    if query is not None and session.get_bind().dialect.name == "postgresql":
        digests = {
            (unit_id, period): (count, total) for unit_id, period, count, total in session.execute(query)
        }
    batch["source_digests"] = digests
    return digests


def _inputs_digest(session: Session, org_unit: OrgUnit, period: str, uses_events: bool) -> str | None:
    """Fingerprint of every source row a run for this unit and period reads, or None if unsupported."""
    batch = _batch(session)
    if batch is None:
        return None
    digests = _source_digests(session, batch)
    if digests is None:
        return None
    by_period = batch.get("source_digests_by_period")
    if by_period is None:
        by_period = {}
        for (unit_id, row_period), item in digests.items():
            by_period.setdefault(row_period, {})[unit_id] = item
        batch["source_digests_by_period"] = by_period
    units = _read_units(session, org_unit, period)
    count = 0
    total = 0
    for unit_id, (rows, fingerprint) in (by_period.get(period) or {}).items():
        if unit_id in units:
            count += rows
            total += fingerprint
    material = f"{count}|{total}"
    if uses_events:
        material += "|" + _event_state(session, batch)["digest"]
    return hashlib.sha256(material.encode()).hexdigest()


def _memo_run(
    session: Session, key: str | None, org_unit: OrgUnit, period: str, uses_events: bool
) -> CalculationRun | None:
    batch = _batch(session) or {}
    revision = batch.get("input_revision")
    if key is None or revision is None:
        return None
    found = session.execute(
        select(
            CalculationRun,
            CalculationRunMemo.revision,
            CalculationRunMemo.config_revision,
            CalculationRunMemo.inputs_digest,
            CalculationRunMemo.quality_scanned_at,
            CalculationRunMemo.valid_until,
        )
        .join(CalculationRunMemo, CalculationRunMemo.calculation_run_id == CalculationRun.id)
        # The stored evidence of a run is large and a verified run is only pointed to; whoever
        # needs the evidence reads it then.
        .options(defer(CalculationRun.config_snapshot), defer(CalculationRun.evidence_manifest))
        .where(CalculationRunMemo.request_key == key, CalculationRun.status == JobStatus.SUCCEEDED.value)
    ).first()
    if found is None:
        return None
    run, stamped_revision, stamped_config, stamped_digest, scanned_at, valid_until = found
    if valid_until is not None and _utc(valid_until) <= datetime.now(UTC):
        return None
    state = {
        "key": key,
        "scanned_at": scanned_at,
        "valid_until": valid_until,
        "config_revision": stamped_config,
        "inputs_digest": stamped_digest,
    }
    if stamped_revision != revision:
        config = batch.get("config_revision")
        if config is None or stamped_config != config or stamped_digest is None:
            return None
        if _inputs_digest(session, org_unit, period, uses_events) != stamped_digest:
            return None
        # The same inputs at a newer revision: stamp it, so the next request needs one lookup.
        session.info.setdefault(MEMO_PENDING_KEY, {})[key] = {"run_id": run.id, "revision": revision, **state}
    session.info.setdefault(MEMO_STATE_KEY, {})[run.id] = state
    return run


def _remember_run(
    session: Session, key: str | None, run: CalculationRun, org_unit: OrgUnit, period: str, uses_events: bool
) -> None:
    batch = _batch(session) or {}
    revision = batch.get("input_revision")
    if key is None or revision is None:
        return
    state = {
        "key": key,
        "scanned_at": None,
        # Only an event-based run has a moment at which the clock alone would change it.
        "valid_until": _event_state(session, batch)["valid_until"] if uses_events else None,
        "config_revision": batch.get("config_revision"),
        "inputs_digest": _inputs_digest(session, org_unit, period, uses_events),
    }
    session.info.setdefault(MEMO_PENDING_KEY, {})[key] = {"run_id": run.id, "revision": revision, **state}
    session.info.setdefault(MEMO_STATE_KEY, {})[run.id] = state


def quality_scan_is_recent(session: Session, run: CalculationRun) -> bool:
    """True when this exact run, on unchanged inputs, was quality-scanned within the last hour."""
    state = (session.info.get(MEMO_STATE_KEY) or {}).get(run.id)
    if state is None or state["scanned_at"] is None:
        return False
    return datetime.now(UTC) - _utc(state["scanned_at"]) < QUALITY_SCAN_REUSE


def note_quality_scanned(session: Session, run: CalculationRun) -> None:
    now = datetime.now(UTC)
    state = (session.info.get(MEMO_STATE_KEY) or {}).get(run.id)
    revision = (_batch(session) or {}).get("input_revision")
    if state is None or revision is None:
        return
    state["scanned_at"] = now
    session.info.setdefault(MEMO_PENDING_KEY, {})[state["key"]] = {"run_id": run.id, "revision": revision, **state}


def flush_run_memos(session: Session) -> None:
    """Write this request's stamps in key order, in one statement, so concurrent views cannot deadlock."""
    pending = session.info.pop(MEMO_PENDING_KEY, None)
    session.info.pop(MEMO_STATE_KEY, None)
    if not pending:
        return
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    elif dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    else:
        return
    session.flush()
    rows = [
        {
            "request_key": key,
            "calculation_run_id": entry["run_id"],
            "revision": entry["revision"],
            "quality_scanned_at": entry["scanned_at"],
            "valid_until": entry["valid_until"],
            "config_revision": entry["config_revision"],
            "inputs_digest": entry["inputs_digest"],
        }
        for key, entry in sorted(pending.items())
    ]
    for start in range(0, len(rows), 500):
        statement = insert(CalculationRunMemo).values(rows[start : start + 500])
        session.execute(
            statement.on_conflict_do_update(
                index_elements=[CalculationRunMemo.request_key],
                set_={
                    "calculation_run_id": statement.excluded.calculation_run_id,
                    "revision": statement.excluded.revision,
                    "quality_scanned_at": statement.excluded.quality_scanned_at,
                    "valid_until": statement.excluded.valid_until,
                    "config_revision": statement.excluded.config_revision,
                    "inputs_digest": statement.excluded.inputs_digest,
                },
            )
        )


def _interval_in_force(valid_from, valid_to, as_of) -> bool:
    if valid_from and as_of < valid_from:
        return False
    if valid_to and as_of > valid_to:
        return False
    return True


FORMULA_VERSION_UNAVAILABLE = "formula_version_unavailable"


@dataclass(frozen=True)
class FormulaVersionDecision:
    """Why one formula version was (or was not) used for an indicator and period.

    The effective date is the period end. Dated history is authoritative: when any version of an
    indicator carries validity dates, only a version in force on the effective date may be used.
    Undated legacy versions are used only for indicators with no dated history, and only when
    the environment's governance policy permits it.
    """

    indicator_id: UUID
    effective_date: date
    rule: str
    version: IndicatorVersion | None = None
    candidate_version_ids: tuple[str, ...] = ()
    policy: str | None = None

    @property
    def available(self) -> bool:
        return self.version is not None

    @property
    def reason_code(self) -> str | None:
        return None if self.available else FORMULA_VERSION_UNAVAILABLE

    def provenance(self, indicator_code: str | None) -> dict:
        version = self.version
        return {
            "indicator_code": indicator_code,
            "indicator_id": str(self.indicator_id),
            "status": "selected" if version is not None else "unavailable",
            "rule": self.rule,
            "reason_code": self.reason_code,
            "effective_date": self.effective_date.isoformat(),
            "indicator_version_id": str(version.id) if version is not None else None,
            "formula_version": version.formula_version if version is not None else None,
            "valid_from": version.valid_from.isoformat() if version is not None and version.valid_from else None,
            "valid_to": version.valid_to.isoformat() if version is not None and version.valid_to else None,
            "candidate_version_ids": list(self.candidate_version_ids),
            "undated_fallback_policy": self.policy,
        }


def _decide_indicator_version(
    indicator_id: UUID,
    rows: list[IndicatorVersion],
    as_of: date,
    policy: str,
    permitted: bool,
) -> FormulaVersionDecision:
    dated = [row for row in rows if row.valid_from or row.valid_to]
    if dated:
        in_force = [row for row in dated if _interval_in_force(row.valid_from, row.valid_to, as_of)]
        candidates = tuple(sorted(str(row.id) for row in in_force))
        if not in_force:
            return FormulaVersionDecision(indicator_id, as_of, "no_dated_version_in_force", policy=policy)
        latest_start = max((row.valid_from or date.min) for row in in_force)
        latest = [row for row in in_force if (row.valid_from or date.min) == latest_start]
        if len(latest) == 1:
            rule = "dated_in_force" if len(in_force) == 1 else "dated_overlap_latest_valid_from"
            return FormulaVersionDecision(indicator_id, as_of, rule, latest[0], candidates, policy)
        current = [row for row in latest if row.is_current]
        if len(current) == 1:
            return FormulaVersionDecision(
                indicator_id, as_of, "dated_tie_resolved_by_current_flag", current[0], candidates, policy
            )
        return FormulaVersionDecision(indicator_id, as_of, "ambiguous_dated_versions", None, candidates, policy)
    if not permitted:
        return FormulaVersionDecision(indicator_id, as_of, "undated_fallback_not_permitted", policy=policy)
    current = [row for row in rows if row.is_current]
    candidates = tuple(sorted(str(row.id) for row in current))
    if len(current) == 1:
        return FormulaVersionDecision(indicator_id, as_of, "undated_current_fallback", current[0], candidates, policy)
    if not current:
        return FormulaVersionDecision(indicator_id, as_of, "no_current_undated_version", policy=policy)
    return FormulaVersionDecision(indicator_id, as_of, "ambiguous_undated_versions", None, candidates, policy)


def resolve_indicator_versions_for_period(
    session: Session,
    period: str,
    loaded: list[IndicatorVersion] | None = None,
) -> dict[UUID, FormulaVersionDecision]:
    settings = get_settings()
    as_of = parse_period(period).end
    versions = loaded if loaded is not None else list(session.scalars(select(IndicatorVersion)).all())
    by_indicator: dict[UUID, list[IndicatorVersion]] = {}
    for version in versions:
        by_indicator.setdefault(version.indicator_id, []).append(version)
    policy = settings.undated_formula_policy
    permitted = settings.undated_formula_fallback_permitted
    return {
        indicator_id: _decide_indicator_version(indicator_id, rows, as_of, policy, permitted)
        for indicator_id, rows in by_indicator.items()
    }


def select_indicator_versions_for_period(
    session: Session,
    period: str,
    loaded: list[IndicatorVersion] | None = None,
) -> list[IndicatorVersion]:
    """Versions that may be calculated for the period. Unavailable indicators are omitted."""
    decisions = resolve_indicator_versions_for_period(session, period, loaded=loaded)
    return [decision.version for decision in decisions.values() if decision.version is not None]


def _current_raw_rows(
    session: Session,
    org_unit_id: UUID,
    period: str,
    source_key: str,
    programme_id: UUID | None,
) -> list[RawAggregateValue]:
    batch = _batch(session)
    if batch is not None:
        rows = list(batch["raw_index"].get((org_unit_id, period, source_key), []))
        if programme_id is not None:
            rows = [row for row in rows if row.programme_id == programme_id]
        return rows
    query = select(RawAggregateValue).where(
        RawAggregateValue.org_unit_id == org_unit_id,
        RawAggregateValue.period == period,
        RawAggregateValue.internal_source_key == source_key,
        RawAggregateValue.is_current.is_(True),
    )
    if programme_id is not None:
        query = query.where(RawAggregateValue.programme_id == programme_id)
    return list(session.scalars(query).all())


def _usable(row: RawAggregateValue | None) -> bool:
    if row is None or row.value is None:
        return False
    if row.value_invalid:
        return False
    if row.absence_reason in ABSENT_REASONS:
        return False
    return True


@dataclass
class _ChildCohort:
    status: str
    cls: AggregationClass | None
    rows: list[tuple[OrgUnit, RawAggregateValue]]
    reason: str | None = None
    expected_count: int = 0
    partial: bool = False


_DISTRICT_RANK = AGGREGATION_CLASS_RANK[AggregationClass.DISTRICT_EQUIVALENT]


def _below_district(unit: OrgUnit) -> bool:
    cls = aggregation_class(unit.level_type)
    return cls is not None and AGGREGATION_CLASS_RANK.get(cls, 99) > _DISTRICT_RANK


def _read_units(session: Session, org_unit: OrgUnit, period: str) -> frozenset:
    """The units whose source rows a run for ``org_unit`` reads (see _child_cohort).

    A unit with district/city peers beneath it reads itself and its descendants down to that
    class; any other unit reads its whole subtree. Fingerprints cover exactly these rows.
    """
    batch = _batch(session)
    cache = batch.setdefault("read_units", {}) if batch is not None else {}
    key = (org_unit.id, period)
    if key not in cache:
        if batch is not None:
            # The level filter does not depend on the period, so it is applied once per unit; each
            # period then checks only those few units for validity (a national run otherwise walks
            # every facility in the country for every period).
            shallow_key = (org_unit.id, "shallow")
            if shallow_key not in cache:
                cache[shallow_key] = [
                    unit
                    for unit in descendants(session, org_unit, include_self=True, active_only=False)
                    if unit.id == org_unit.id or not _below_district(unit)
                ]
            units = [unit for unit in cache[shallow_key] if unit_in_period(unit, period)]
        else:
            units = [
                unit
                for unit in descendants(session, org_unit, include_self=True, period=period)
                if unit.id == org_unit.id or not _below_district(unit)
            ]
        # "Has district/city peers beneath it" is the same test _child_cohort applies.
        if not any(
            unit.id != org_unit.id and aggregation_class(unit.level_type) == AggregationClass.DISTRICT_EQUIVALENT
            for unit in units
        ):
            units = descendants(session, org_unit, include_self=True, period=period)
        cache[key] = frozenset(unit.id for unit in units)
    return cache[key]


def _child_cohort(
    session: Session,
    children: list[OrgUnit],
    period: str,
    source_key: str,
    programme_id: UUID | None,
    allow_partial: bool = False,
) -> _ChildCohort:
    """Resolve one source key from descendants at a single, complete aggregation class.

    With ``allow_partial`` (an owner-approved ``reporting_units`` indicator) the units that report
    are summed and the cohort records how many of the expected units that is.

    Districts and cities are peers (one class). Genuinely different classes, such as
    district plus facility rows, are rejected rather than combined.
    """
    grouped: dict[AggregationClass | None, list[tuple[OrgUnit, RawAggregateValue]]] = {}
    batch = _batch(session)
    if batch is not None:
        # Only units holding a row can contribute; visit those instead of every descendant.
        index = batch.setdefault("rows_by_period_key", {})
        if (period, source_key) not in index:
            by_unit: dict[UUID, list[RawAggregateValue]] = {}
            for (unit_id, row_period, key), group in batch["raw_index"].items():
                if row_period == period and key == source_key:
                    by_unit[unit_id] = group
            index[(period, source_key)] = by_unit
        with_rows = index[(period, source_key)]
        candidates = [unit for unit in children if unit.id in with_rows]
    else:
        candidates = children
    # District/city peers are an expected reporting level. Where a parent has them, it reads its
    # district/city-level (and shallower) rows only: sub-county and facility rows are their
    # components, are loaded on demand, and never stand in for them. A national or regional figure
    # therefore cannot change because someone opened a district and its facilities were loaded.
    expected_cache = batch.setdefault("expected_cohorts", {}) if batch is not None else {}
    children_key = (len(children), children[0].id if children else None, children[-1].id if children else None)
    structural_key = (*children_key, "structural_districts")
    if structural_key not in expected_cache:
        expected_cache[structural_key] = top_units_of_class(children, AggregationClass.DISTRICT_EQUIVALENT)
    if expected_cache[structural_key]:
        candidates = [unit for unit in candidates if not _below_district(unit)]
    for unit in candidates:
        rows = _current_raw_rows(session, unit.id, period, source_key, programme_id)
        if len(rows) > 1:
            return _ChildCohort(
                "ambiguous_source",
                aggregation_class(unit.level_type),
                [(unit, row) for row in rows],
                "Multiple current child source rows exist for the requested programme and category context.",
            )
        row = rows[0] if rows else None
        if _usable(row):
            grouped.setdefault(aggregation_class(unit.level_type), []).append((unit, row))
    if not grouped:
        return _ChildCohort("missing", None, [], "No source row.")
    if len(grouped) > 1:
        if None in grouped:
            return _ChildCohort(
                "mixed_levels",
                None,
                [item for rows in grouped.values() for item in rows],
                "Parent and descendant rows cannot be mixed.",
            )
        # Facility rows loaded on demand (D-068) sit below districts that hold their own rows.
        # Only the class nearest the parent is summed; deeper rows are its components and are
        # never added to it, so nothing is double counted and no class stands in for another.
        cls = min(grouped, key=lambda item: AGGREGATION_CLASS_RANK.get(item, 99))
        rows = grouped[cls]
    else:
        cls, rows = next(iter(grouped.items()))
    cohort_key = (*children_key, cls)
    if cohort_key not in expected_cache:
        expected_cache[cohort_key] = frozenset(unit.id for unit in top_units_of_class(children, cls))
    expected_ids = expected_cache[cohort_key]
    present_ids = {unit.id for unit, _ in rows}
    if not present_ids <= expected_ids:
        return _ChildCohort(
            "mixed_levels",
            cls,
            rows,
            "Overlapping units of one aggregation class cannot be summed without double counting.",
        )
    if present_ids != expected_ids:
        if allow_partial:
            for unit in children:
                if unit.id not in expected_ids - present_ids:
                    continue
                if any(
                    row.value_invalid for row in _current_raw_rows(session, unit.id, period, source_key, programme_id)
                ):
                    return _ChildCohort(
                        "incomplete",
                        cls,
                        rows,
                        "An invalid peer source is not non-reporting and cannot contribute zero.",
                        expected_count=len(expected_ids),
                    )
            # An approved non-reporting policy is not permission to interpret a failed or
            # unrequested extraction as no doses/deaths. Certify every absent peer first.
            from app.integrations.dhis2.periods import months_in
            from app.services.period_rollup import _coverage_jobs, _missing_month_coverage

            months = months_in(parse_period(period))
            coverage_cache = batch.setdefault("source_coverage_jobs", {}) if batch is not None else {}
            jobs = coverage_cache.get(months)
            if jobs is None:
                jobs = _coverage_jobs(session, months)
                coverage_cache[months] = jobs
            version_set = {row.mapping_version for _, row in rows}
            complete = len(version_set) == 1 and all(
                _missing_month_coverage(jobs, programme_id, unit_id, source_key, next(iter(version_set)), set(months))
                is not None
                for unit_id in expected_ids - present_ids
            )
            if not complete:
                return _ChildCohort(
                    "incomplete",
                    cls,
                    rows,
                    "Non-reporting peers lack successful extraction coverage; missing is not zero.",
                    expected_count=len(expected_ids),
                )
            return _ChildCohort(
                "ok",
                cls,
                rows,
                f"{len(present_ids)} of {len(expected_ids)} units reported; the others contribute nothing.",
                expected_count=len(expected_ids),
                partial=True,
            )
        return _ChildCohort("incomplete", cls, rows, "Incomplete child coverage at a consistent aggregation level.")
    return _ChildCohort("ok", cls, rows, expected_count=len(expected_ids))


def resolve_source_key(
    session: Session,
    org_unit: OrgUnit,
    period: str,
    source_key: str,
    *,
    policy: str = SourceAggregationPolicy.DIRECT_OR_COMPLETE_CHILDREN.value,
    programme_id: UUID | None = None,
) -> SourceResolution:
    direct_rows = _current_raw_rows(session, org_unit.id, period, source_key, programme_id)
    if len(direct_rows) > 1:
        return SourceResolution(
            None,
            "ambiguous_source",
            policy,
            org_unit.level_type,
            row_ids=[row.id for row in direct_rows],
            mapping_versions=sorted({row.mapping_version for row in direct_rows if row.mapping_version}),
            reason="Multiple current source rows exist for the requested programme and category context.",
        )
    direct = direct_rows[0] if direct_rows else None
    if _usable(direct):
        return SourceResolution(
            value=float(direct.value),
            status="ok",
            policy="direct",
            level=_class_value(org_unit),
            unit_ids=[org_unit.id],
            row_ids=[direct.id],
            mapping_versions=[direct.mapping_version] if direct.mapping_version else [],
        )
    if policy == SourceAggregationPolicy.DIRECT_ONLY.value:
        return SourceResolution(
            None,
            "missing",
            policy,
            org_unit.level_type,
            reason="No direct percentage exists for the requested geography.",
        )
    children = descendants(session, org_unit, include_self=False, period=period)
    cohort = _child_cohort(session, children, period, source_key, programme_id)
    level = cohort.cls.value if cohort.cls else None
    if cohort.status != "ok":
        return SourceResolution(
            None,
            cohort.status,
            policy,
            level,
            unit_ids=[unit.id for unit, _ in cohort.rows],
            row_ids=[row.id for _, row in cohort.rows],
            reason=cohort.reason,
        )
    mapping_versions = sorted({row.mapping_version for _, row in cohort.rows if row.mapping_version})
    if len(mapping_versions) > 1:
        return SourceResolution(
            None,
            "mixed_mapping_versions",
            policy,
            level,
            unit_ids=[unit.id for unit, _ in cohort.rows],
            row_ids=[row.id for _, row in cohort.rows],
            mapping_versions=mapping_versions,
            reason="Current child rows use incompatible mapping versions.",
        )
    return SourceResolution(
        sum(float(row.value) for _, row in cohort.rows),
        "ok",
        "children",
        level,
        unit_ids=[unit.id for unit, _ in cohort.rows],
        row_ids=[row.id for _, row in cohort.rows],
        mapping_versions=mapping_versions,
    )


def sum_source_key(
    session: Session,
    org_unit: OrgUnit,
    period: str,
    source_key: str,
    programme_id: UUID | None = None,
) -> float | None:
    resolved = resolve_source_key(session, org_unit, period, source_key, programme_id=programme_id)
    return resolved.value


def _class_value(org_unit: OrgUnit) -> str | None:
    cls = aggregation_class(org_unit.level_type)
    return cls.value if cls else org_unit.level_type


_COHORT_REASON_CODES = {
    "ambiguous_source": UnavailableReason.AMBIGUOUS_SOURCE.value,
    "mixed_levels": UnavailableReason.MIXED_LEVELS.value,
    "incomplete": UnavailableReason.INCOMPLETE_CHILDREN.value,
    "missing": UnavailableReason.MISSING_COMPONENT.value,
}


def resolve_common_scope(
    session: Session,
    org_unit: OrgUnit,
    period: str,
    keys: list[str],
    *,
    programme_id: UUID | None,
    required: set[str] | None = None,
    allow_partial: bool = False,
) -> ScopeResolution:
    """Resolve every aggregate component of a formula at one shared scope.

    Valid scopes are: every component from a direct row at the requested geography, or
    every component from one complete child cohort at the same aggregation class with
    a compatible mapping version. A parent row for one component and child rows for
    another is never combined. When no common scope exists the result is unavailable.
    """
    keys = list(dict.fromkeys(keys))
    required_keys = set(keys) if required is None else set(required) & set(keys)
    if not keys:
        return ScopeResolution(
            "missing",
            None,
            None,
            reason="No source components are configured.",
            reason_code=UnavailableReason.MISSING_COMPONENT.value,
        )

    direct: dict[str, RawAggregateValue] = {}
    for key in keys:
        rows = _current_raw_rows(session, org_unit.id, period, key, programme_id)
        if len(rows) > 1:
            return ScopeResolution(
                "ambiguous_source",
                "direct",
                _class_value(org_unit),
                row_ids=[row.id for row in rows],
                missing=[key],
                reason="Multiple current source rows exist for the requested programme and category context.",
                reason_code=UnavailableReason.AMBIGUOUS_SOURCE.value,
            )
        if rows and _usable(rows[0]):
            direct[key] = rows[0]

    if len(direct) == len(keys):
        return _direct_scope(org_unit, direct, missing=[])

    children = descendants(session, org_unit, include_self=False, period=period)
    cohorts = {
        key: _child_cohort(session, children, period, key, programme_id, allow_partial=allow_partial) for key in keys
    }
    for key, cohort in cohorts.items():
        if cohort.status == "ambiguous_source":
            return ScopeResolution(
                "ambiguous_source",
                "children",
                cohort.cls.value if cohort.cls else None,
                row_ids=[row.id for _, row in cohort.rows],
                missing=[key],
                reason=cohort.reason,
                reason_code=UnavailableReason.AMBIGUOUS_SOURCE.value,
            )

    absent = [key for key in keys if key not in direct and cohorts[key].status == "missing"]
    absent_required = [key for key in absent if key in required_keys]
    if absent_required:
        return ScopeResolution(
            "missing",
            None,
            None,
            missing=absent_required,
            reason="Required composite components are missing.",
            reason_code=UnavailableReason.MISSING_COMPONENT.value,
        )
    considered = [key for key in keys if key not in absent]
    if not considered:
        return ScopeResolution(
            "missing",
            None,
            None,
            missing=absent,
            reason="No source components are available.",
            reason_code=UnavailableReason.MISSING_COMPONENT.value,
        )
    if all(key in direct for key in considered):
        return _direct_scope(org_unit, {key: direct[key] for key in considered}, missing=absent)

    failing = {key: cohorts[key] for key in considered if cohorts[key].status != "ok"}
    if failing:
        direct_only = [key for key, cohort in failing.items() if cohort.status == "missing" and key in direct]
        if direct_only:
            child_scoped = [key for key in considered if key not in direct_only]
            return ScopeResolution(
                "incompatible_scope",
                None,
                None,
                missing=sorted(direct_only),
                reason=(
                    f"Components {', '.join(sorted(direct_only))} exist only as direct rows for this geography, "
                    f"while {', '.join(sorted(child_scoped))} require child aggregation. "
                    "No common aggregation scope exists."
                ),
                reason_code=UnavailableReason.INCOMPATIBLE_SCOPE.value,
            )
        key, cohort = next(iter(failing.items()))
        return ScopeResolution(
            cohort.status,
            "children",
            cohort.cls.value if cohort.cls else None,
            row_ids=[row.id for _, row in cohort.rows],
            unit_ids=[unit.id for unit, _ in cohort.rows],
            missing=[key],
            reason=cohort.reason,
            reason_code=_COHORT_REASON_CODES.get(cohort.status, UnavailableReason.MISSING_COMPONENT.value),
        )

    classes = {cohorts[key].cls for key in considered}
    if len(classes) > 1:
        return ScopeResolution(
            "incompatible_scope",
            "children",
            None,
            missing=considered,
            reason="Components resolve at different aggregation levels. No common aggregation scope exists.",
            reason_code=UnavailableReason.INCOMPATIBLE_SCOPE.value,
        )
    rows = [row for key in considered for _, row in cohorts[key].rows]
    versions = sorted({row.mapping_version for row in rows if row.mapping_version})
    cls = classes.pop()
    if len(versions) > 1:
        return ScopeResolution(
            "mixed_mapping_versions",
            "children",
            cls.value if cls else None,
            row_ids=[row.id for row in rows],
            mapping_versions=versions,
            missing=considered,
            reason="Components use incompatible mapping versions.",
            reason_code=UnavailableReason.MIXED_MAPPING_VERSIONS.value,
        )
    partial = [cohorts[key] for key in considered if cohorts[key].partial]
    return ScopeResolution(
        "ok",
        "children_reporting" if partial else "children",
        cls.value if cls else None,
        reason=partial[0].reason if partial else None,
        values={key: sum(float(row.value) for _, row in cohorts[key].rows) for key in considered},
        row_ids=[row.id for row in rows],
        unit_ids=sorted({unit.id for key in considered for unit, _ in cohorts[key].rows}, key=str),
        mapping_versions=versions,
        missing=absent,
    )


def _direct_scope(org_unit: OrgUnit, rows: dict[str, RawAggregateValue], *, missing: list[str]) -> ScopeResolution:
    versions = sorted({row.mapping_version for row in rows.values() if row.mapping_version})
    if len(versions) > 1:
        return ScopeResolution(
            "mixed_mapping_versions",
            "direct",
            _class_value(org_unit),
            row_ids=[row.id for row in rows.values()],
            mapping_versions=versions,
            missing=sorted(rows),
            reason="Components use incompatible mapping versions.",
            reason_code=UnavailableReason.MIXED_MAPPING_VERSIONS.value,
        )
    return ScopeResolution(
        "ok",
        "direct",
        _class_value(org_unit),
        values={key: float(row.value) for key, row in rows.items()},
        row_ids=[row.id for row in rows.values()],
        unit_ids=[org_unit.id],
        mapping_versions=versions,
        missing=missing,
    )


def _scope_unavailable(scope: ScopeResolution, **extra) -> Measure:
    code = scope.reason_code or UnavailableReason.MISSING_COMPONENT.value
    quality = PerformanceStatus.BLUE.value if code in QUALITY_SCOPE_REASONS else PerformanceStatus.NA.value
    return Measure(
        None,
        None,
        None,
        PerformanceStatus.NA.value,
        None,
        quality,
        scope.reason or "Required composite components are missing.",
        missing_components=list(scope.missing),
        aggregation_policy=scope.policy,
        aggregation_level=scope.level,
        source_row_ids=[str(item) for item in scope.row_ids],
        reason_code=code,
        **extra,
    )


def _event_follow_up_end(period: str, timely: str | None) -> date | None:
    cohort_end = parse_period(period).end
    if timely == "notification":
        return cohort_end + timedelta(days=NOTIFICATION_FOLLOW_UP_DAYS)
    if timely == "review":
        return cohort_end + timedelta(days=REVIEW_FOLLOW_UP_DAYS)
    return None


def _event_count(session: Session, org_unit: OrgUnit, period: str, spec: dict) -> EventCountResult:
    event_type = spec.get("event_type")
    completed_only = spec.get("completed_only", True)
    timely = spec.get("timely")
    batch = _batch(session)
    if batch is not None:
        subtree_ids = batch.setdefault("subtree_ids", {})
        subtree_key = (org_unit.id, period)
        if subtree_key not in subtree_ids:
            subtree_ids[subtree_key] = frozenset(
                unit.id for unit in descendants(session, org_unit, include_self=True, period=period)
            )
        units = subtree_ids[subtree_key]
    else:
        units = {unit.id for unit in descendants(session, org_unit, include_self=True, period=period)}
    batch = _batch(session)
    if batch is not None:
        # Events are indexed by unit and each period's in-scope death cohort is resolved once per
        # request; a national screen otherwise rescans every event for every indicator and unit.
        cohorts = batch.setdefault("mpdsr_cohorts", {})
        if period not in cohorts:
            # The period is parsed once, not once per event (the same test as in_death_cohort).
            cohort_period = parse_period(period)
            start, end = cohort_period.start, cohort_period.end
            in_scope = mpdsr_scope(session, as_of=end)
            by_unit: dict = {}
            for event in batch["events"]:
                death = event.death_date
                if death is not None and start <= death <= end and in_scope(event):
                    by_unit.setdefault(event.org_unit_id, []).append(event)
            cohorts[period] = by_unit
        by_unit = cohorts[period]
        rows = [event for unit_id in units for event in by_unit.get(unit_id, ())]
    else:
        rows = scoped_mpdsr_events(session, org_unit, period, unit_ids=units)
    matched: list[RawEventSnapshot] = []
    for event in rows:
        payload = event.data_values or {}
        if payload.get("event_type") != event_type:
            continue
        if completed_only and not is_completed(event):
            continue
        if timely == "notification":
            if not chronology_valid_notification(event.death_date, event.notification_date):
                continue
            if not notification_timely(event.death_date, event.notification_date):
                continue
        if timely == "review":
            if not chronology_valid_review(event.death_date, event.review_date):
                continue
            if not review_timely(event.death_date, event.review_date):
                continue
        matched.append(event)
    coverage = evaluate_event_coverage(
        session,
        org_unit=org_unit,
        period=period,
        required_end=_event_follow_up_end(period, timely),
    )
    event_ids = sorted(str(event.id) for event in matched)
    if matched:
        return EventCountResult(len(matched), event_ids, coverage)
    if coverage.get("status") == EventCoverageStatus.VERIFIED.value:
        return EventCountResult(0, [], coverage)
    return EventCountResult(
        None,
        [],
        coverage,
        reason=(
            "No matching MPDSR events were found, and the empty cohort cannot be treated as zero: "
            f"{coverage.get('reason')}"
        ),
    )


def _event_unavailable(result: EventCountResult, denominator: float | None = None) -> Measure:
    return Measure(
        None,
        denominator,
        None,
        PerformanceStatus.NA.value,
        None,
        PerformanceStatus.NA.value,
        result.reason,
        aggregation_policy="event_cohort",
        reason_code=UnavailableReason.EVENT_COVERAGE_UNVERIFIED.value,
        event_coverage=result.coverage,
    )


def evaluate_formula(
    session: Session,
    *,
    org_unit: OrgUnit,
    period: str,
    version: IndicatorVersion,
    programme_id: UUID | None,
) -> Measure:
    raw_spec = version.formula_spec or INDICATOR_BY_CODE.get(session.get(Indicator, version.indicator_id).code, {}).get(
        "formula_spec"
    )
    if not raw_spec:
        return Measure(
            None,
            None,
            None,
            PerformanceStatus.NA.value,
            None,
            PerformanceStatus.NA.value,
            "Formula specification is missing.",
            reason_code=UnavailableReason.FORMULA_MISSING.value,
        )
    try:
        spec = validate_formula_spec(raw_spec)
        if version.classification_spec:
            validate_classification_spec(version.classification_spec)
    except FormulaValidationError as exc:
        return Measure(
            None,
            None,
            None,
            PerformanceStatus.NA.value,
            None,
            PerformanceStatus.NA.value,
            str(exc),
            reason_code=UnavailableReason.FORMULA_MISSING.value,
        )

    kind = spec.get("kind")
    require_all = spec.get("require_all_components", True)
    allow_reporting = spec.get("child_coverage") == "reporting_units"
    programme = session.get(Programme, programme_id) if programme_id is not None else None
    if programme is not None and programme.code == "MPDSR" and not get_settings().mpdsr_reporting_units_approved:
        allow_reporting = False

    classification = dict(version.classification_spec or {})
    classification.setdefault("precision", version.display_precision)

    if kind == FormulaKind.COUNT.value:
        numerator_spec = spec.get("numerator")
        if numerator_spec and numerator_spec.get("mode") == "event_count":
            result = _event_count(session, org_unit, period, numerator_spec)
            if result.count is None:
                return _event_unavailable(result)
            return Measure(
                float(result.count),
                1,
                float(result.count),
                PerformanceStatus.NA.value,
                PerformanceStatus.NA.value,
                None,
                aggregation_policy="event_cohort",
                aggregation_level=_class_value(org_unit),
                event_snapshot_ids=result.event_ids,
                event_coverage=result.coverage,
            )
        keys = spec.get("source_keys") or []
        scope = resolve_common_scope(
            session,
            org_unit,
            period,
            keys,
            programme_id=programme_id,
            required=set(keys) if require_all else set(),
            allow_partial=allow_reporting,
        )
        if not scope.ok:
            return _scope_unavailable(scope)
        total = sum(scope.values.values())
        return Measure(
            total,
            1,
            total,
            PerformanceStatus.NA.value,
            PerformanceStatus.NA.value,
            None,
            source_row_ids=[str(item) for item in scope.row_ids],
            aggregation_policy=scope.policy,
            aggregation_level=scope.level,
            missing_components=list(scope.missing),
        )

    if kind == FormulaKind.DIRECT_PERCENTAGE.value:
        resolved = resolve_source_key(
            session,
            org_unit,
            period,
            spec["source_key"],
            policy=SourceAggregationPolicy.DIRECT_ONLY.value,
            programme_id=programme_id,
        )
        if resolved.value is None:
            return Measure(
                None,
                None,
                None,
                PerformanceStatus.NA.value,
                None,
                PerformanceStatus.NA.value,
                resolved.reason or "Direct percentage source is missing.",
                aggregation_policy=SourceAggregationPolicy.DIRECT_ONLY.value,
                reason_code=(
                    UnavailableReason.AMBIGUOUS_SOURCE.value
                    if resolved.status == "ambiguous_source"
                    else UnavailableReason.MISSING_COMPONENT.value
                ),
            )
        status = classify(resolved.value, classification)
        if spec.get("over_100") == Over100Behaviour.NON_ASSESSABLE.value and resolved.value > 100:
            status = PerformanceStatus.BLUE.value
        performance = None if status == PerformanceStatus.BLUE.value else status
        quality = status if status == PerformanceStatus.BLUE.value else None
        return Measure(
            resolved.value,
            100,
            resolved.value,
            status,
            performance,
            quality,
            aggregation_policy=SourceAggregationPolicy.DIRECT_ONLY.value,
            aggregation_level=_class_value(org_unit),
            source_row_ids=[str(item) for item in resolved.row_ids],
        )

    if kind == FormulaKind.DROPOUT.value:
        scope = resolve_common_scope(
            session,
            org_unit,
            period,
            [spec["first_key"], spec["final_key"]],
            programme_id=programme_id,
            allow_partial=allow_reporting,
        )
        if not scope.ok:
            return _scope_unavailable(scope)
        first = scope.values[spec["first_key"]]
        final = scope.values[spec["final_key"]]
        source_ids = [str(item) for item in scope.row_ids]
        if first == 0:
            return Measure(
                first - final,
                first,
                None,
                PerformanceStatus.NA.value,
                None,
                PerformanceStatus.BLUE.value,
                "Dose1 is zero; dropout is non-assessable.",
                source_row_ids=source_ids,
                aggregation_policy=scope.policy,
                aggregation_level=scope.level,
                reason_code=UnavailableReason.DENOMINATOR_ZERO.value,
            )
        raw = ((first - final) / first) * 100
        status = classify(raw, classification)
        return Measure(
            first - final,
            first,
            raw,
            status,
            status if status != PerformanceStatus.NA.value else None,
            None,
            source_row_ids=source_ids,
            aggregation_policy=scope.policy,
            aggregation_level=scope.level,
        )

    numerator_spec = spec.get("numerator")
    den_spec = spec.get("denominator") or {}
    event_numerator = bool(numerator_spec and numerator_spec.get("mode") == "event_count")
    numerator_keys = [] if event_numerator else list(spec.get("numerator_keys") or [])
    denominator_keys = list(den_spec.get("source_keys") or []) if den_spec.get("mode") == "source_keys" else []

    scope: ScopeResolution | None = None
    if numerator_keys or denominator_keys:
        required = set(denominator_keys) | (set(numerator_keys) if require_all else set())
        scope = resolve_common_scope(
            session,
            org_unit,
            period,
            numerator_keys + denominator_keys,
            programme_id=programme_id,
            required=required,
            allow_partial=allow_reporting,
        )

    event_result: EventCountResult | None = None
    numerator: float | None = None
    if event_numerator:
        event_result = _event_count(session, org_unit, period, numerator_spec)
        numerator = float(event_result.count) if event_result.count is not None else None
    elif scope is not None and scope.ok:
        present = [scope.values[key] for key in numerator_keys if key in scope.values]
        numerator = sum(present) if present else None

    lineage = dict(
        event_snapshot_ids=event_result.event_ids if event_result else [],
        event_coverage=event_result.coverage if event_result else None,
    )

    population_year = None
    population_version_id = None
    facility_entry_id = None
    denominator: float | None = None
    target: TargetDenominator | None = None
    if den_spec.get("mode") == "population":
        # One authoritative resolution of population year, coefficient and period fraction.
        target = resolve_target_denominator(
            session,
            org_unit,
            period_key=period,
            coefficient=den_spec.get("coefficient") or version.denominator_coefficient,
            programme_id=programme_id,
            period_adjust=bool(den_spec.get("period_adjust") or version.period_adjustment),
        )
        if not target.ok:
            return Measure(
                numerator,
                None,
                None,
                PerformanceStatus.NA.value,
                None,
                PerformanceStatus.BLUE.value,
                target.reason or "Population unavailable.",
                population_year=target.population_year,
                population_version_id=target.population_version_id,
                facility_population_entry_id=target.facility_population_entry_id,
                missing_components=list(scope.missing) if scope is not None else [],
                reason_code=target.reason_code or UnavailableReason.POPULATION_UNAVAILABLE.value,
                denominator_provenance=target.provenance(),
                **lineage,
            )
        denominator = target.value
        population_year = target.population_year
        population_version_id = None if target.facility_population_entry_id else target.population_version_id
        facility_entry_id = target.facility_population_entry_id
    elif denominator_keys and scope is not None and scope.ok:
        denominator = sum(scope.values[key] for key in denominator_keys if key in scope.values)

    population_lineage = dict(
        population_year=population_year,
        population_version_id=population_version_id,
        facility_population_entry_id=facility_entry_id,
        denominator_provenance=target.provenance() if target is not None else None,
    )

    if scope is not None and not scope.ok:
        measure = _scope_unavailable(scope, **population_lineage, **lineage)
        if event_numerator:
            # The event numerator does not depend on the aggregate scope; keep its verified value.
            measure.numerator = numerator
            measure.aggregation_policy = measure.aggregation_policy or "event_cohort"
        return measure
    if event_result is not None and event_result.count is None:
        measure = _event_unavailable(event_result, denominator)
        measure.population_year = population_year
        measure.population_version_id = population_version_id
        measure.facility_population_entry_id = facility_entry_id
        if scope is not None:
            measure.source_row_ids = [str(item) for item in scope.row_ids]
        return measure

    scope_lineage = dict(
        aggregation_policy=scope.policy if scope is not None else ("event_cohort" if event_numerator else None),
        aggregation_level=scope.level if scope is not None else _class_value(org_unit),
        source_row_ids=[str(item) for item in scope.row_ids] if scope is not None else [],
        missing_components=list(scope.missing) if scope is not None else [],
    )

    if numerator is None:
        return Measure(
            None,
            denominator,
            None,
            PerformanceStatus.NA.value,
            None,
            PerformanceStatus.NA.value,
            "Numerator source is missing.",
            reason_code=UnavailableReason.MISSING_COMPONENT.value,
            **population_lineage,
            **scope_lineage,
            **lineage,
        )
    if denominator is None:
        return Measure(
            numerator,
            None,
            None,
            PerformanceStatus.NA.value,
            None,
            PerformanceStatus.BLUE.value,
            "Denominator is missing.",
            reason_code=UnavailableReason.DENOMINATOR_MISSING.value,
            **population_lineage,
            **scope_lineage,
            **lineage,
        )
    if denominator == 0:
        return Measure(
            numerator,
            denominator,
            None,
            PerformanceStatus.NA.value,
            None,
            PerformanceStatus.NA.value,
            "Denominator is zero; result is non-assessable, not zero percent.",
            reason_code=UnavailableReason.DENOMINATOR_ZERO.value,
            **population_lineage,
            **scope_lineage,
            **lineage,
        )

    raw = (numerator / denominator) * float(version.multiplier)
    status = classify(raw, classification)
    blue_reason = None
    quality_status = None
    if spec.get("over_100") == Over100Behaviour.NON_ASSESSABLE.value and raw > 100:
        status = PerformanceStatus.BLUE.value
        blue_reason = "Bounded proportion exceeds 100%."
        quality_status = PerformanceStatus.BLUE.value
    if spec.get("reconciliation_blue") and denominator > 0 and numerator > denominator:
        status = PerformanceStatus.BLUE.value
        blue_reason = "Line-list count exceeds aggregate reported deaths. Reconciliation is required."
        quality_status = PerformanceStatus.BLUE.value
    performance = status if status not in {PerformanceStatus.BLUE.value, PerformanceStatus.NA.value} else None
    return Measure(
        numerator,
        denominator,
        raw,
        status,
        performance,
        quality_status,
        blue_reason,
        **population_lineage,
        **scope_lineage,
        **lineage,
    )


def _batch_mapping_ids(session: Session) -> dict | None:
    """Mapping IDs recorded in the provenance of every row in the batch, read once."""
    batch = _batch(session)
    if batch is None or "raw_row_ids" not in batch:
        return None
    cached = batch.get("mapping_id_by_row")
    if cached is None:
        cached = {}
        ids = batch["raw_row_ids"]
        for start in range(0, len(ids), 5000):
            chunk = ids[start : start + 5000]
            for row_id, mapping_id in session.execute(
                select(RawAggregateValue.id, RawAggregateValue.provenance["mapping_id"].as_string()).where(
                    RawAggregateValue.id.in_(chunk)
                )
            ):
                cached[row_id] = mapping_id
        batch["mapping_id_by_row"] = cached
    return cached


def _mapping_for_source_row(
    session: Session,
    row: RawAggregateValue,
    programme_id: UUID,
    cache: dict | None = None,
) -> SourceMapping | None:
    """Resolve the mapping that produced a source row.

    Many rows share one mapping (the same key across facilities and periods). ``cache`` memoises the
    lookup for the duration of one calculation run, during which the mapping table cannot change;
    without it, lineage issues one query per row.
    """
    batch_ids = _batch_mapping_ids(session)
    if batch_ids is not None and row.id in batch_ids:
        mapping_id = batch_ids[row.id]
    else:
        mapping_id = (row.provenance or {}).get("mapping_id")
    key = (
        programme_id,
        row.internal_source_key,
        row.mapping_version,
        row.dhis2_item_uid,
        row.category_option_combo_uid or "",
        str(mapping_id) if mapping_id else None,
    )
    if cache is not None and key in cache:
        return cache[key]
    resolved = _resolve_mapping_for_source_row(session, row, programme_id, mapping_id)
    if cache is not None:
        cache[key] = resolved
    return resolved


def _resolve_mapping_for_source_row(
    session: Session, row: RawAggregateValue, programme_id: UUID, mapping_id
) -> SourceMapping | None:
    if mapping_id:
        try:
            referenced = session.get(SourceMapping, UUID(str(mapping_id)))
        except ValueError:
            referenced = None
        if (
            referenced is not None
            and referenced.programme_id == programme_id
            and referenced.internal_source_key == row.internal_source_key
            and referenced.mapping_version == row.mapping_version
            and referenced.dhis2_item_uid == row.dhis2_item_uid
            and (referenced.category_option_combo_uid or "") == (row.category_option_combo_uid or "")
        ):
            return referenced
    return session.scalar(
        select(SourceMapping).where(
            SourceMapping.programme_id == programme_id,
            SourceMapping.internal_source_key == row.internal_source_key,
            SourceMapping.mapping_version == row.mapping_version,
            SourceMapping.dhis2_item_uid == row.dhis2_item_uid,
            SourceMapping.category_option_combo_uid == (row.category_option_combo_uid or None),
        )
    )


def _lineage_provenance(session: Session, rows: list[RawAggregateValue], loaded: dict) -> None:
    """Add to ``loaded`` the provenance of source rows this run has not read yet, in one query.

    The calculation batch defers the provenance column; reading it attribute by attribute costs one
    query per source row, which is thousands of queries for a national view.
    """
    wanted = [row.id for row in rows if row.id not in loaded]
    for start in range(0, len(wanted), 5000):
        chunk = wanted[start : start + 5000]
        for row_id, provenance in session.execute(
            select(RawAggregateValue.id, RawAggregateValue.provenance).where(RawAggregateValue.id.in_(chunk))
        ):
            loaded[row_id] = provenance


def _utc(value: datetime | None) -> datetime | None:
    """SQLite returns naive timestamps for reloaded rows; compare everything as UTC."""
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _source_lineage(
    session: Session,
    source_row_ids: list[str],
    programme_id: UUID,
    mapping_cache: dict | None = None,
) -> tuple[list[RawAggregateValue], list[str], str | None, datetime | None]:
    parsed_ids: list[UUID] = []
    for value in source_row_ids:
        try:
            parsed_ids.append(UUID(str(value)))
        except ValueError:
            continue
    # Source rows are normally already loaded by the calculation batch; only rows the session has
    # not seen are read from the database.
    rows: list[RawAggregateValue] = []
    missing: list[UUID] = []
    for row_id in parsed_ids:
        loaded = session.identity_map.get(identity_key(RawAggregateValue, row_id))
        if loaded is not None:
            rows.append(loaded)
        else:
            missing.append(row_id)
    if missing:
        rows.extend(session.scalars(select(RawAggregateValue).where(RawAggregateValue.id.in_(missing))).all())
    mapping_ids: set[str] = set()
    versions = {row.mapping_version for row in rows if row.mapping_version}
    freshness = [_utc(row.source_freshness_at) for row in rows if row.source_freshness_at]
    for row in rows:
        mapping = _mapping_for_source_row(session, row, programme_id, mapping_cache)
        if mapping is not None:
            mapping_ids.add(str(mapping.id))
    mapping_version = next(iter(versions)) if len(versions) == 1 else ("mixed" if versions else None)
    return rows, sorted(mapping_ids), mapping_version, min(freshness) if freshness else None


def run_calculation(
    session: Session,
    *,
    org_unit: OrgUnit,
    period: str,
    user: User | None,
    programme_codes: list[str] | None = None,
    indicator_codes: list[str] | None = None,
) -> CalculationRun:
    started = datetime.now(UTC)
    batch = _batch(session)
    if batch and period in (batch.get("version_decisions_by_period") or {}):
        decisions = batch["version_decisions_by_period"][period]
    else:
        decisions = resolve_indicator_versions_for_period(session, period)
    versions = sorted(
        (decision.version for decision in decisions.values() if decision.version is not None),
        key=lambda row: str(row.id),
    )
    uses_events = batch is not None and _request_uses_events(batch, versions, programme_codes, indicator_codes)
    memo_key = _memo_key(org_unit, period, programme_codes, indicator_codes)
    verified = _memo_run(session, memo_key, org_unit, period, uses_events)
    if verified is not None:
        session.info.setdefault(REUSED_RUNS_KEY, set()).add(verified.id)
        return verified
    mapping_cache: dict = {}
    programme_id = None
    if programme_codes:
        programme = session.scalar(select(Programme).where(Programme.code == programme_codes[0]))
        programme_id = programme.id if programme else None
    if batch is not None:
        # The mapping table cannot change during one request, so lineage lookups are shared
        # across every run in the batch.
        mapping_cache = batch.setdefault("mapping_cache", {})
    fingerprint = _input_fingerprint(
        session,
        org_unit=org_unit,
        period=period,
        programme_codes=programme_codes,
        indicator_codes=indicator_codes,
        versions=versions,
        decisions=decisions,
    )
    if fingerprint is not None:
        reused = _reusable_run(session, org_unit, period, fingerprint)
        if reused is not None:
            session.info.setdefault(REUSED_RUNS_KEY, set()).add(reused.id)
            _remember_run(session, memo_key, reused, org_unit, period, uses_events)
            return reused
    run = CalculationRun(
        id=uuid4(),
        geography_org_unit_id=org_unit.id,
        period=period,
        programme_id=programme_id,
        initiated_by_user_id=user.id if user else None,
        status=JobStatus.RUNNING.value,
        started_at=started,
        software_version=SOFTWARE_VERSION,
        aggregation_policy=SourceAggregationPolicy.DIRECT_OR_COMPLETE_CHILDREN.value,
        idempotency_key=fingerprint,
    )
    session.add(run)
    session.flush()
    # One load per batch (or per standalone run). The session identity map is weak, so repeated
    # session.get() calls would reload these rows for every run.
    indicator_rows = (batch or {}).get("indicators") or {
        row.id: row for row in session.scalars(select(Indicator)).all()
    }
    programme_rows = (batch or {}).get("programmes") or {
        row.id: row for row in session.scalars(select(Programme)).all()
    }
    version_selection = []
    for decision in decisions.values():
        indicator = indicator_rows.get(decision.indicator_id)
        if indicator is None or not indicator.active:
            continue
        indicator_programme = programme_rows.get(indicator.programme_id)
        if programme_codes and indicator_programme and indicator_programme.code not in programme_codes:
            continue
        if indicator_codes and indicator.code not in indicator_codes:
            continue
        version_selection.append(decision.provenance(indicator.code))
    version_selection.sort(key=lambda item: item["indicator_code"] or "")
    selection_by_version = {
        item["indicator_version_id"]: item for item in version_selection if item["indicator_version_id"]
    }
    snapshot_versions = []
    raw_ids: list[str] = []
    mapping_ids: list[str] = []
    source_lineage: dict[str, dict] = {}
    provenance_by_row: dict = {}
    population_version_ids: set[str] = set()
    facility_population_entry_ids: set[str] = set()
    source_freshness_values: list[datetime] = []
    extracted_values: list[datetime] = []
    event_snapshot_ids: set[str] = set()
    try:
        for version in versions:
            indicator = indicator_rows.get(version.indicator_id)
            if indicator is None or not indicator.active:
                continue
            programme = programme_rows.get(indicator.programme_id)
            if programme_codes and programme and programme.code not in programme_codes:
                continue
            if indicator_codes and indicator.code not in indicator_codes:
                continue
            measure = evaluate_formula(
                session,
                org_unit=org_unit,
                period=period,
                version=version,
                programme_id=indicator.programme_id,
            )
            raw_ids.extend(measure.source_row_ids)
            event_snapshot_ids.update(measure.event_snapshot_ids)
            source_rows, actual_mapping_ids, mapping_version, source_freshness = _source_lineage(
                session, measure.source_row_ids, indicator.programme_id, mapping_cache
            )
            mapping_ids.extend(actual_mapping_ids)
            if source_freshness is not None:
                source_freshness_values.append(source_freshness)
            extracted_values.extend(_utc(row.extracted_at) for row in source_rows if row.extracted_at)
            _lineage_provenance(session, source_rows, provenance_by_row)
            for row in source_rows:
                provenance = provenance_by_row.get(row.id) or {}
                source_mapping = _mapping_for_source_row(session, row, indicator.programme_id, mapping_cache)
                source_lineage[str(row.id)] = {
                    "id": str(row.id),
                    "programme_id": str(row.programme_id) if row.programme_id else None,
                    "source_system": row.source_system,
                    "source_key": row.internal_source_key,
                    "org_unit_id": str(row.org_unit_id),
                    "period": row.period,
                    "value": float(row.value) if row.value is not None else None,
                    "mapping_version": row.mapping_version,
                    "mapping_id": str(source_mapping.id) if source_mapping else None,
                    "checksum": row.checksum,
                    "extracted_at": row.extracted_at.isoformat() if row.extracted_at else None,
                    "source_freshness_at": (row.source_freshness_at.isoformat() if row.source_freshness_at else None),
                    "derivation": provenance.get("derivation"),
                    "components": provenance.get("components"),
                    "coverage_job_ids": provenance.get("coverage_job_ids"),
                }
            if measure.population_version_id:
                population_version_ids.add(str(measure.population_version_id))
            if measure.facility_population_entry_id:
                facility_population_entry_ids.add(str(measure.facility_population_entry_id))
            display = display_value(measure.raw_value, version.display_precision, version.unit)
            if (
                version.unit
                and "percent" not in version.unit.lower()
                and version.unit != "%"
                and display
                and display.endswith("%")
            ):
                display = display.rstrip("%")
            session.add(
                CalculatedValue(
                    calculation_run_id=run.id,
                    indicator_version_id=version.id,
                    org_unit_id=org_unit.id,
                    period=period,
                    numerator=measure.numerator,
                    denominator=measure.denominator,
                    raw_value=measure.raw_value,
                    display_value=display,
                    status=measure.status,
                    performance_status=measure.performance_status,
                    quality_status=measure.quality_status,
                    unit=version.unit,
                    direction=version.direction,
                    target=version.target,
                    display_precision=version.display_precision,
                    population_year=measure.population_year,
                    population_version_id=measure.population_version_id,
                    facility_population_entry_id=measure.facility_population_entry_id,
                    mapping_version=mapping_version,
                    source_freshness_at=source_freshness,
                    methodology_ref=indicator.code,
                    blue_reason=measure.blue_reason,
                    aggregation_policy=measure.aggregation_policy,
                    aggregation_level=measure.aggregation_level,
                    source_row_ids=measure.source_row_ids,
                    source_mapping_ids=actual_mapping_ids,
                    software_version=SOFTWARE_VERSION,
                    missing_components=measure.missing_components or None,
                    reason_code=measure.reason_code,
                    event_snapshot_ids=measure.event_snapshot_ids or None,
                    event_coverage=measure.event_coverage,
                    denominator_provenance=measure.denominator_provenance,
                )
            )
            selection = selection_by_version.get(str(version.id)) or {}
            snapshot_versions.append(
                {
                    "indicator_code": indicator.code,
                    "indicator_id": str(indicator.id),
                    "indicator_version_id": str(version.id),
                    "formula_version": version.formula_version,
                    "formula_version_rule": selection.get("rule"),
                    "valid_from": selection.get("valid_from"),
                    "valid_to": selection.get("valid_to"),
                    "effective_date": selection.get("effective_date"),
                    "formula_spec": version.formula_spec,
                    "classification_spec": version.classification_spec,
                    "mapping_version": mapping_version,
                    "source_row_ids": measure.source_row_ids,
                    "source_mapping_ids": actual_mapping_ids,
                    "event_snapshot_ids": measure.event_snapshot_ids,
                    "event_coverage_status": (measure.event_coverage or {}).get("status"),
                    "reason_code": measure.reason_code,
                    "population_version_id": (
                        str(measure.population_version_id) if measure.population_version_id else None
                    ),
                    "facility_population_entry_id": (
                        str(measure.facility_population_entry_id) if measure.facility_population_entry_id else None
                    ),
                    "source_freshness_at": source_freshness.isoformat() if source_freshness else None,
                }
            )
        run.status = JobStatus.SUCCEEDED.value
        run.finished_at = datetime.now(UTC)
        run.duration_ms = int((run.finished_at - started).total_seconds() * 1000)
        indicator_version_ids = sorted(item["indicator_version_id"] for item in snapshot_versions)
        run.indicator_set_version = hashlib.sha256("|".join(indicator_version_ids).encode()).hexdigest()[:16]
        run_mapping_versions = {item["mapping_version"] for item in snapshot_versions if item.get("mapping_version")}
        run.mapping_version = (
            next(iter(run_mapping_versions))
            if len(run_mapping_versions) == 1
            else ("mixed" if run_mapping_versions else None)
        )
        run.population_version_id = (
            UUID(next(iter(population_version_ids))) if len(population_version_ids) == 1 else None
        )
        run.source_extracted_at = max(extracted_values) if extracted_values else None
        run.config_snapshot = {
            "software_version": SOFTWARE_VERSION,
            "org_unit_id": str(org_unit.id),
            "period": period,
            "programme_codes": programme_codes,
            "requester_user_id": str(user.id) if user else None,
            "indicator_set_version": run.indicator_set_version,
            "aggregation_policy": run.aggregation_policy,
            "indicator_versions": snapshot_versions,
            "raw_row_ids": sorted(set(raw_ids)),
            "mapping_ids": sorted(set(mapping_ids)),
            "source_rows": [source_lineage[key] for key in sorted(source_lineage)],
            "population_version_ids": sorted(population_version_ids),
            "facility_population_entry_ids": sorted(facility_population_entry_ids),
            "source_freshness_at": (min(source_freshness_values).isoformat() if source_freshness_values else None),
            "event_snapshot_ids": sorted(event_snapshot_ids),
            "formula_version_policy": {
                "effective_date": parse_period(period).end.isoformat(),
                "effective_date_rule": "period_end",
                "undated_fallback_policy": get_settings().undated_formula_policy,
            },
            "formula_version_selection": version_selection,
            "unavailable_indicators": [
                {
                    "indicator_code": item["indicator_code"],
                    "reason_code": item["reason_code"],
                    "rule": item["rule"],
                }
                for item in version_selection
                if item["status"] == "unavailable"
            ],
        }
        run.evidence_manifest = run.config_snapshot
        session.flush()
        if fingerprint is not None:
            _remember_run(session, memo_key, run, org_unit, period, uses_events)
        return run
    except Exception:
        run.status = JobStatus.FAILED.value
        run.error_code = "calculation_failed"
        run.finished_at = datetime.now(UTC)
        session.flush()
        raise

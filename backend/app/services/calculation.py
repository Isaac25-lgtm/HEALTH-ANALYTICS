from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain.enums import (
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
    CalculatedValue,
    CalculationRun,
    Indicator,
    IndicatorVersion,
    OrgUnit,
    Programme,
    RawAggregateValue,
    RawEventSnapshot,
    SourceMapping,
    User,
)
from app.services.classification import classify, display_value
from app.services.event_coverage import evaluate_event_coverage
from app.services.geography import descendants, top_units_of_class
from app.services.mpdsr import (
    chronology_valid_notification,
    chronology_valid_review,
    in_death_cohort,
    is_completed,
    notification_timely,
    review_timely,
)
from app.services.mpdsr_events import event_in_mpdsr_scope, scoped_mpdsr_events
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


def prepare_calculation_batch(
    session: Session,
    *,
    org_unit: OrgUnit,
    periods: list[str],
) -> dict:
    units = descendants(session, org_unit, include_self=True)
    unit_ids = [unit.id for unit in units]
    raw_rows = list(
        session.scalars(
            select(RawAggregateValue).where(
                RawAggregateValue.org_unit_id.in_(unit_ids),
                RawAggregateValue.period.in_(periods),
                RawAggregateValue.is_current.is_(True),
            )
        ).all()
    )
    events = list(
        session.scalars(
            select(RawEventSnapshot).where(
                RawEventSnapshot.org_unit_id.in_(unit_ids),
                RawEventSnapshot.is_current.is_(True),
                RawEventSnapshot.source_connector == "tracker",
            )
        ).all()
    )
    raw_index: dict[tuple, list[RawAggregateValue]] = {}
    for row in raw_rows:
        raw_index.setdefault((row.org_unit_id, row.period, row.internal_source_key), []).append(row)
    loaded_versions = list(session.scalars(select(IndicatorVersion)).all())
    decisions_by_period = {
        key: resolve_indicator_versions_for_period(session, key, loaded=loaded_versions) for key in periods
    }
    batch = {
        "units": units,
        "unit_by_id": {unit.id: unit for unit in units},
        "raw_index": raw_index,
        "events": events,
        "version_decisions_by_period": decisions_by_period,
        "indicators": {row.id: row for row in session.scalars(select(Indicator)).all()},
        "programmes": {row.id: row for row in session.scalars(select(Programme)).all()},
        "versions_by_period": {
            key: [item.version for item in decisions.values() if item.version is not None]
            for key, decisions in decisions_by_period.items()
        },
        "query_batches": 4,
    }
    session.info[BATCH_INFO_KEY] = batch
    return batch


def clear_calculation_batch(session: Session) -> None:
    session.info.pop(BATCH_INFO_KEY, None)


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


def _child_cohort(
    session: Session,
    children: list[OrgUnit],
    period: str,
    source_key: str,
    programme_id: UUID | None,
) -> _ChildCohort:
    """Resolve one source key from descendants at a single, complete aggregation class.

    Districts and cities are peers (one class). Genuinely different classes, such as
    district plus facility rows, are rejected rather than combined.
    """
    grouped: dict[AggregationClass | None, list[tuple[OrgUnit, RawAggregateValue]]] = {}
    for unit in children:
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
        return _ChildCohort(
            "mixed_levels",
            None,
            [item for rows in grouped.values() for item in rows],
            "Parent and descendant rows cannot be mixed.",
        )
    cls, rows = next(iter(grouped.items()))
    expected = top_units_of_class(children, cls)
    expected_ids = {unit.id for unit in expected}
    present_ids = {unit.id for unit, _ in rows}
    if not present_ids <= expected_ids:
        return _ChildCohort(
            "mixed_levels",
            cls,
            rows,
            "Overlapping units of one aggregation class cannot be summed without double counting.",
        )
    if present_ids != expected_ids:
        return _ChildCohort("incomplete", cls, rows, "Incomplete child coverage at a consistent aggregation level.")
    return _ChildCohort("ok", cls, rows)


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
    children = descendants(session, org_unit, include_self=False)
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
    resolved = resolve_source_key(
        session, org_unit, period, source_key, programme_id=programme_id
    )
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

    children = descendants(session, org_unit, include_self=False)
    cohorts = {key: _child_cohort(session, children, period, key, programme_id) for key in keys}
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
    return ScopeResolution(
        "ok",
        "children",
        cls.value if cls else None,
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
    units = {unit.id for unit in descendants(session, org_unit, include_self=True)}
    batch = _batch(session)
    if batch is not None:
        rows = [event for event in batch["events"] if event.org_unit_id in units]
        rows = [event for event in rows if event_in_mpdsr_scope(session, event, as_of=parse_period(period).end)]
        rows = [event for event in rows if in_death_cohort(event, period)]
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
    raw_spec = version.formula_spec or INDICATOR_BY_CODE.get(
        session.get(Indicator, version.indicator_id).code, {}
    ).get("formula_spec")
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
    rows = (
        list(session.scalars(select(RawAggregateValue).where(RawAggregateValue.id.in_(parsed_ids))).all())
        if parsed_ids
        else []
    )
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
    mapping_cache: dict = {}
    programme_id = None
    if programme_codes:
        programme = session.scalar(select(Programme).where(Programme.code == programme_codes[0]))
        programme_id = programme.id if programme else None
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
    )
    session.add(run)
    session.flush()
    batch = _batch(session)
    if batch and period in (batch.get("version_decisions_by_period") or {}):
        decisions = batch["version_decisions_by_period"][period]
    else:
        decisions = resolve_indicator_versions_for_period(session, period)
    versions = sorted(
        (decision.version for decision in decisions.values() if decision.version is not None),
        key=lambda row: str(row.id),
    )
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
            for row in source_rows:
                source_mapping = _mapping_for_source_row(session, row, indicator.programme_id, mapping_cache)
                source_lineage[str(row.id)] = {
                    "id": str(row.id),
                    "programme_id": str(row.programme_id) if row.programme_id else None,
                    "source_system": row.source_system,
                    "source_key": row.internal_source_key,
                    "mapping_version": row.mapping_version,
                    "mapping_id": str(source_mapping.id) if source_mapping else None,
                    "checksum": row.checksum,
                    "extracted_at": row.extracted_at.isoformat() if row.extracted_at else None,
                    "source_freshness_at": (
                        row.source_freshness_at.isoformat() if row.source_freshness_at else None
                    ),
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
                        str(measure.facility_population_entry_id)
                        if measure.facility_population_entry_id
                        else None
                    ),
                    "source_freshness_at": source_freshness.isoformat() if source_freshness else None,
                }
            )
        run.status = JobStatus.SUCCEEDED.value
        run.finished_at = datetime.now(UTC)
        run.duration_ms = int((run.finished_at - started).total_seconds() * 1000)
        indicator_version_ids = sorted(item["indicator_version_id"] for item in snapshot_versions)
        run.indicator_set_version = hashlib.sha256("|".join(indicator_version_ids).encode()).hexdigest()[:16]
        run_mapping_versions = {
            item["mapping_version"] for item in snapshot_versions if item.get("mapping_version")
        }
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
            "source_freshness_at": (
                min(source_freshness_values).isoformat() if source_freshness_values else None
            ),
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
        return run
    except Exception:
        run.status = JobStatus.FAILED.value
        run.error_code = "calculation_failed"
        run.finished_at = datetime.now(UTC)
        session.flush()
        raise

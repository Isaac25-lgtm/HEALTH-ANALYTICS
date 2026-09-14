from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain.enums import (
    AbsenceReason,
    ApprovalStatus,
    EventCoverageStatus,
    EventStatus,
    QualitySeverity,
    QualityStatus,
    UnavailableReason,
    aggregation_class,
)
from app.domain.indicator_catalog import QUALITY_RULE_CATALOG
from app.models import (
    CalculatedValue,
    CalculationRun,
    DataQualityFlag,
    FacilityPopulationEntry,
    FreshnessSnapshot,
    Indicator,
    IndicatorVersion,
    OrgUnit,
    Programme,
    QualityRule,
    RawAggregateValue,
    RawEventSnapshot,
    SourceMapping,
)
from app.services.geography import descendants, has_overlapping_units
from app.services.mpdsr import (
    chronology_valid_notification,
    chronology_valid_review,
    event_display_status,
    in_death_cohort,
    is_completed,
    review_timely,
)

RULES = {row["code"]: row for row in QUALITY_RULE_CATALOG}
REOPEN_FROM_RESOLVED = True
EVENT_RULES = {
    "ACTIVE_MPDSR_WORKFLOW",
    "NOTIFICATION_BEFORE_DEATH",
    "REVIEW_BEFORE_DEATH",
    "REVIEW_INTERVAL_OUT_OF_RANGE",
    "MISSING_CAUSE",
    "MISSING_CRITICAL_DATE",
    "POSSIBLE_DUPLICATE_EVENT",
}


def _fingerprint(
    *,
    rule: str,
    org_unit_id: UUID | None,
    period: str | None,
    source_key: str | None,
    indicator_id: UUID | None,
    extra: str = "",
) -> str:
    material = "|".join(
        [
            rule,
            str(org_unit_id or ""),
            period or "",
            source_key or "",
            str(indicator_id or ""),
            extra,
        ]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _enabled_rules(session: Session) -> dict[str, QualityRule]:
    rows = session.scalars(select(QualityRule).where(QualityRule.enabled.is_(True))).all()
    return {row.code: row for row in rows}


def _upsert_flag(
    session: Session,
    *,
    rule: str,
    enabled: dict[str, QualityRule],
    org_unit_id: UUID | None,
    period: str | None,
    explanation: str,
    evidence: dict,
    severity: str | None = None,
    category: str | None = None,
    indicator_id: UUID | None = None,
    programme_id: UUID | None = None,
    source_key: str | None = None,
    event_uid: str | None = None,
    calculation_run_id: UUID | None = None,
    sync_job_id: UUID | None = None,
    extra: str = "",
) -> DataQualityFlag | None:
    db_rule = enabled.get(rule)
    if db_rule is None:
        return None
    catalog = RULES.get(rule, {})
    now = datetime.now(UTC)
    fingerprint = _fingerprint(
        rule=rule,
        org_unit_id=org_unit_id,
        period=period,
        source_key=source_key,
        indicator_id=indicator_id,
        extra=extra,
    )
    existing = session.scalar(
        select(DataQualityFlag).where(
            DataQualityFlag.fingerprint == fingerprint,
            DataQualityFlag.status.in_([QualityStatus.OPEN.value, QualityStatus.ACKNOWLEDGED.value]),
        )
    )
    if existing is not None:
        existing.last_detected_at = now
        existing.calculation_run_id = calculation_run_id or existing.calculation_run_id
        existing.explanation = explanation
        existing.evidence = evidence
        return existing
    resolved = session.scalar(
        select(DataQualityFlag)
        .where(
            DataQualityFlag.fingerprint == fingerprint,
            DataQualityFlag.status == QualityStatus.RESOLVED.value,
        )
        .order_by(DataQualityFlag.last_detected_at.desc())
    )
    if resolved is not None and REOPEN_FROM_RESOLVED:
        resolved.status = QualityStatus.OPEN.value
        resolved.reopen_count = (resolved.reopen_count or 0) + 1
        resolved.last_detected_at = now
        resolved.calculation_run_id = calculation_run_id or resolved.calculation_run_id
        resolved.explanation = explanation
        resolved.evidence = evidence
        resolved.resolved_at = None
        return resolved
    suppressed = session.scalar(
        select(DataQualityFlag).where(
            DataQualityFlag.fingerprint == fingerprint,
            DataQualityFlag.status == QualityStatus.SUPPRESSED.value,
        )
    )
    if suppressed is not None:
        return None
    flag = DataQualityFlag(
        fingerprint=fingerprint,
        rule_id=rule,
        rule_version=db_rule.rule_version,
        category=category or db_rule.category or catalog.get("category"),
        severity=severity or db_rule.severity or catalog.get("severity") or QualitySeverity.WARNING.value,
        status=QualityStatus.OPEN.value,
        org_unit_id=org_unit_id,
        programme_id=programme_id,
        indicator_id=indicator_id,
        period=period,
        source_key=source_key,
        event_uid=event_uid,
        evidence=evidence,
        explanation=explanation,
        calculation_run_id=calculation_run_id,
        sync_job_id=sync_job_id,
        first_detected_at=now,
        last_detected_at=now,
    )
    session.add(flag)
    return flag


def scan_quality(
    session: Session,
    *,
    org_unit: OrgUnit,
    period: str,
    calculation_run: CalculationRun | None = None,
) -> list[DataQualityFlag]:
    enabled = _enabled_rules(session)
    created: list[DataQualityFlag] = []
    scanners = [
        _scan_calculated,
        _scan_raw,
        _scan_events,
        _scan_mappings,
        _scan_freshness,
        _scan_facility_population,
        _scan_parent_child,
        _scan_stale_and_spike,
    ]
    for scanner in scanners:
        for flag in scanner(session, org_unit, period, calculation_run, enabled):
            if flag is not None:
                created.append(flag)
    session.flush()
    if calculation_run is not None:
        open_count = session.scalars(
            select(DataQualityFlag).where(
                DataQualityFlag.calculation_run_id == calculation_run.id,
                DataQualityFlag.status.in_([QualityStatus.OPEN.value, QualityStatus.ACKNOWLEDGED.value]),
            )
        ).all()
        calculation_run.quality_flag_count = len(open_count)
    session.flush()
    return created


def _scan_calculated(session, org_unit, period, run, enabled) -> list[DataQualityFlag | None]:
    flags: list[DataQualityFlag | None] = []
    if run is None:
        return flags
    rows = session.scalars(select(CalculatedValue).where(CalculatedValue.calculation_run_id == run.id)).all()
    for row in rows:
        version = session.get(IndicatorVersion, row.indicator_version_id)
        indicator = session.get(Indicator, version.indicator_id) if version else None
        spec = version.formula_spec if version else {}
        unit = row.unit or ""
        bounded = bool(spec and spec.get("bounded_proportion"))
        common = dict(
            enabled=enabled,
            org_unit_id=row.org_unit_id,
            period=period,
            indicator_id=indicator.id if indicator else None,
            calculation_run_id=run.id,
            programme_id=indicator.programme_id if indicator else None,
        )
        if bounded and row.raw_value is not None and float(row.raw_value) > 100 and unit in {"%"}:
            flags.append(
                _upsert_flag(
                    session,
                    rule="BOUNDED_PROPORTION_OVER_100",
                    explanation=RULES["BOUNDED_PROPORTION_OVER_100"]["explanation"],
                    evidence={"raw_value": float(row.raw_value), "unit": unit},
                    **common,
                )
            )
        if spec and spec.get("over_100") == "flag_only" and row.raw_value is not None and float(row.raw_value) > 100:
            flags.append(
                _upsert_flag(
                    session,
                    rule="BOUNDED_PROPORTION_OVER_100",
                    severity=QualitySeverity.WARNING.value,
                    explanation="The value exceeds 100% and is retained. A definition or reporting review is required.",
                    evidence={"raw_value": float(row.raw_value), "retained": True},
                    extra="retained",
                    **common,
                )
            )
        if (
            row.numerator is not None
            and row.denominator is not None
            and float(row.denominator) > 0
            and float(row.numerator) > float(row.denominator)
            and unit == "%"
            and bounded
        ):
            flags.append(
                _upsert_flag(
                    session,
                    rule="NUMERATOR_GT_DENOMINATOR",
                    explanation=RULES["NUMERATOR_GT_DENOMINATOR"]["explanation"],
                    evidence={"numerator": float(row.numerator), "denominator": float(row.denominator)},
                    **common,
                )
            )
        if row.denominator is None and row.status in {"n_a", "blue"}:
            flags.append(
                _upsert_flag(
                    session,
                    rule="MISSING_DENOMINATOR",
                    explanation=row.blue_reason or RULES["MISSING_DENOMINATOR"]["explanation"],
                    evidence={"indicator": indicator.code if indicator else None},
                    **common,
                )
            )
        if row.reason_code == UnavailableReason.POPULATION_RULE_MISSING.value:
            flags.append(
                _upsert_flag(
                    session,
                    rule="POPULATION_RULE_MISSING",
                    explanation=row.blue_reason or RULES["POPULATION_RULE_MISSING"]["explanation"],
                    evidence={"reason_code": row.reason_code, "period": period},
                    **common,
                )
            )
        elif row.blue_reason and "Population" in (row.blue_reason or ""):
            flags.append(
                _upsert_flag(
                    session,
                    rule="MISSING_POPULATION",
                    explanation=RULES["MISSING_POPULATION"]["explanation"],
                    evidence={"reason": row.blue_reason},
                    **common,
                )
            )
        if row.reason_code in {
            UnavailableReason.INCOMPATIBLE_SCOPE.value,
            UnavailableReason.MIXED_LEVELS.value,
            UnavailableReason.MIXED_MAPPING_VERSIONS.value,
        }:
            flags.append(
                _upsert_flag(
                    session,
                    rule="INCOMPATIBLE_AGGREGATION_SCOPE",
                    explanation=row.blue_reason or RULES["INCOMPATIBLE_AGGREGATION_SCOPE"]["explanation"],
                    evidence={
                        "reason_code": row.reason_code,
                        "components": list(row.missing_components or []),
                        "aggregation_level": row.aggregation_level,
                    },
                    **common,
                )
            )
        coverage = row.event_coverage or {}
        if coverage.get("status") == EventCoverageStatus.UNVERIFIED.value:
            flags.append(
                _upsert_flag(
                    session,
                    rule="MPDSR_EVENT_COVERAGE_UNVERIFIED",
                    explanation=RULES["MPDSR_EVENT_COVERAGE_UNVERIFIED"]["explanation"],
                    evidence={
                        "value_available": row.raw_value is not None,
                        "coverage_reason": coverage.get("reason"),
                        "requirement": coverage.get("requirement"),
                    },
                    **common,
                )
            )
        if row.denominator is not None and float(row.denominator) == 0:
            flags.append(
                _upsert_flag(
                    session,
                    rule="DENOMINATOR_ZERO",
                    explanation=RULES["DENOMINATOR_ZERO"]["explanation"],
                    evidence={"numerator": float(row.numerator) if row.numerator is not None else None},
                    **common,
                )
            )
        if row.blue_reason and "exceeds aggregate" in (row.blue_reason or "").lower():
            flags.append(
                _upsert_flag(
                    session,
                    rule="LINELIST_GT_AGGREGATE",
                    explanation=RULES["LINELIST_GT_AGGREGATE"]["explanation"],
                    evidence={"numerator": float(row.numerator or 0), "denominator": float(row.denominator or 0)},
                    **common,
                )
            )
            flags.append(
                _upsert_flag(
                    session,
                    rule="AGGREGATE_EVENT_MISMATCH",
                    explanation=RULES["AGGREGATE_EVENT_MISMATCH"]["explanation"],
                    evidence={"difference": float(row.numerator or 0) - float(row.denominator or 0)},
                    **common,
                )
            )
        if row.missing_components:
            flags.append(
                _upsert_flag(
                    session,
                    rule="INCOMPLETE_COMPOSITE",
                    explanation=RULES["INCOMPLETE_COMPOSITE"]["explanation"],
                    evidence={"missing_components": list(row.missing_components)},
                    **common,
                )
            )
        if row.reason_code == UnavailableReason.INCOMPLETE_CHILDREN.value or (
            row.blue_reason and "Incomplete child" in (row.blue_reason or "")
        ):
            flags.append(
                _upsert_flag(
                    session,
                    rule="INCOMPLETE_CHILD_COVERAGE",
                    explanation=RULES["INCOMPLETE_CHILD_COVERAGE"]["explanation"],
                    evidence={"aggregation_level": row.aggregation_level},
                    **common,
                )
            )
    return flags


def _prior_nonzero(
    session: Session,
    org_unit_id: UUID,
    source_key: str | None,
    period: str,
    programme_id: UUID | None,
) -> bool:
    if not source_key:
        return False
    query = select(RawAggregateValue).where(
        RawAggregateValue.org_unit_id == org_unit_id,
        RawAggregateValue.internal_source_key == source_key,
        RawAggregateValue.is_current.is_(True),
        RawAggregateValue.period != period,
    )
    if programme_id is not None:
        query = query.where(RawAggregateValue.programme_id == programme_id)
    rows = session.scalars(query).all()
    return any(row.value is not None and float(row.value) > 0 for row in rows)


def _scan_raw(session, org_unit, period, run, enabled) -> list[DataQualityFlag | None]:
    flags: list[DataQualityFlag | None] = []
    units = descendants(session, org_unit, include_self=True)
    ids = [unit.id for unit in units]
    query = select(RawAggregateValue).where(
        RawAggregateValue.org_unit_id.in_(ids),
        RawAggregateValue.period == period,
        RawAggregateValue.is_current.is_(True),
    )
    if run is not None and run.programme_id is not None:
        query = query.where(RawAggregateValue.programme_id == run.programme_id)
    rows = session.scalars(query).all()
    unexpected = enabled.get("UNEXPECTED_ZERO")
    unexpected_config = (unexpected.config or {}) if unexpected is not None else {}
    high_volume_keys = set(unexpected_config.get("high_volume_source_keys") or [])
    high_volume_orgs = {str(item) for item in (unexpected_config.get("high_volume_org_unit_ids") or [])}
    for row in rows:
        common = dict(
            enabled=enabled,
            org_unit_id=row.org_unit_id,
            period=period,
            source_key=row.internal_source_key,
            calculation_run_id=run.id if run else None,
            programme_id=row.programme_id,
        )
        if row.absence_reason == AbsenceReason.NO_SOURCE_ROW.value:
            flags.append(
                _upsert_flag(
                    session,
                    rule="NO_DATA_VS_REPORTED_ZERO",
                    explanation=RULES["NO_DATA_VS_REPORTED_ZERO"]["explanation"],
                    evidence={"absence_reason": row.absence_reason, "value": None},
                    **common,
                )
            )
        if row.value_invalid or row.absence_reason == AbsenceReason.INVALID_VALUE.value:
            flags.append(
                _upsert_flag(
                    session,
                    rule="INVALID_SOURCE_VALUE",
                    explanation=RULES["INVALID_SOURCE_VALUE"]["explanation"],
                    evidence={"absence_reason": row.absence_reason, "value_invalid": True},
                    **common,
                )
            )
        reported_zero = row.absence_reason == AbsenceReason.REPORTED_ZERO.value or (
            row.value is not None and float(row.value) == 0 and not row.value_invalid
        )
        if reported_zero:
            contextual = (
                _prior_nonzero(
                    session,
                    row.org_unit_id,
                    row.internal_source_key,
                    period,
                    row.programme_id,
                )
                or (row.internal_source_key in high_volume_keys)
                or str(row.org_unit_id) in high_volume_orgs
                or bool(unexpected_config.get("peer_rule"))
            )
            if contextual:
                flags.append(
                    _upsert_flag(
                        session,
                        rule="UNEXPECTED_ZERO",
                        explanation=RULES["UNEXPECTED_ZERO"]["explanation"],
                        evidence={
                            "value": 0,
                            "source_key": row.internal_source_key,
                            "prior_nonzero": True,
                        },
                        **common,
                    )
                )
        if row.absence_reason == AbsenceReason.STALE.value:
            flags.append(
                _upsert_flag(
                    session,
                    rule="STALE_REPORTING",
                    explanation=RULES["STALE_REPORTING"]["explanation"],
                    evidence={"extracted_at": row.extracted_at.isoformat() if row.extracted_at else None},
                    **common,
                )
            )
    return flags


def _event_associated_with_period(event: RawEventSnapshot, period: str) -> bool:
    if in_death_cohort(event, period):
        return True
    from app.domain.periods import date_in_period, parse_period

    spec = parse_period(period)
    if event.occurred_at and date_in_period(event.occurred_at.date(), spec):
        return True
    if event.notification_date and date_in_period(event.notification_date, spec):
        return True
    if event.review_date and date_in_period(event.review_date, spec):
        return True
    return False


def _scan_events(session, org_unit, period, run, enabled) -> list[DataQualityFlag | None]:
    flags: list[DataQualityFlag | None] = []
    mpdsr = session.scalar(select(Programme).where(Programme.code == "MPDSR"))
    if mpdsr is None:
        return flags
    if run is not None and run.programme_id is not None and run.programme_id != mpdsr.id:
        return flags
    units = {unit.id for unit in descendants(session, org_unit, include_self=True)}
    events = session.scalars(
        select(RawEventSnapshot).where(
            RawEventSnapshot.org_unit_id.in_(units),
            RawEventSnapshot.is_current.is_(True),
        )
    ).all()
    signatures: dict[tuple, list[RawEventSnapshot]] = {}
    for event in events:
        payload = event.data_values or {}
        in_cohort = in_death_cohort(event, period)
        associated = _event_associated_with_period(event, period)
        if event.death_date is not None and not in_cohort:
            continue
        if event.death_date is None and not associated:
            continue
        common = dict(
            enabled=enabled,
            org_unit_id=event.org_unit_id,
            period=period,
            calculation_run_id=run.id if run else None,
            programme_id=mpdsr.id,
            extra=event.event_uid,
        )
        if event.status == EventStatus.ACTIVE.value and in_cohort:
            flags.append(
                _upsert_flag(
                    session,
                    rule="ACTIVE_MPDSR_WORKFLOW",
                    event_uid=event.event_uid,
                    explanation=RULES["ACTIVE_MPDSR_WORKFLOW"]["explanation"],
                    evidence={"status": event.status, "display": event_display_status(event.status)},
                    **common,
                )
            )
        if event.notification_date and event.death_date and not chronology_valid_notification(
            event.death_date, event.notification_date
        ):
            flags.append(
                _upsert_flag(
                    session,
                    rule="NOTIFICATION_BEFORE_DEATH",
                    event_uid=event.event_uid,
                    explanation=RULES["NOTIFICATION_BEFORE_DEATH"]["explanation"],
                    evidence={
                        "death_date": event.death_date.isoformat(),
                        "notification_date": event.notification_date.isoformat(),
                    },
                    **common,
                )
            )
        if event.review_date and event.death_date and not chronology_valid_review(event.death_date, event.review_date):
            flags.append(
                _upsert_flag(
                    session,
                    rule="REVIEW_BEFORE_DEATH",
                    event_uid=event.event_uid,
                    explanation=RULES["REVIEW_BEFORE_DEATH"]["explanation"],
                    evidence={
                        "death_date": event.death_date.isoformat(),
                        "review_date": event.review_date.isoformat(),
                    },
                    **common,
                )
            )
        if (
            is_completed(event)
            and event.death_date
            and event.review_date
            and chronology_valid_review(event.death_date, event.review_date)
            and not review_timely(event.death_date, event.review_date)
        ):
            flags.append(
                _upsert_flag(
                    session,
                    rule="REVIEW_INTERVAL_OUT_OF_RANGE",
                    event_uid=event.event_uid,
                    explanation=RULES["REVIEW_INTERVAL_OUT_OF_RANGE"]["explanation"],
                    evidence={"days": (event.review_date - event.death_date).days},
                    **common,
                )
            )
        if is_completed(event) and str(payload.get("event_type", "")).endswith("review") and not payload.get("cause"):
            flags.append(
                _upsert_flag(
                    session,
                    rule="MISSING_CAUSE",
                    event_uid=event.event_uid,
                    explanation=RULES["MISSING_CAUSE"]["explanation"],
                    evidence={"event_type": payload.get("event_type"), "cause_present": False},
                    **common,
                )
            )
        event_type = str(payload.get("event_type") or "")
        if associated and event.death_date is None:
            flags.append(
                _upsert_flag(
                    session,
                    rule="MISSING_CRITICAL_DATE",
                    event_uid=event.event_uid,
                    explanation=RULES["MISSING_CRITICAL_DATE"]["explanation"],
                    evidence={"missing": "death_date", "event_type": event_type or None},
                    **common,
                )
            )
        if in_cohort:
            sig = (event.org_unit_id, event.death_date, payload.get("event_type"))
            signatures.setdefault(sig, []).append(event)
    for sig, group in signatures.items():
        if sig[1] is None or len(group) <= 1:
            continue
        flags.append(
            _upsert_flag(
                session,
                rule="POSSIBLE_DUPLICATE_EVENT",
                enabled=enabled,
                org_unit_id=group[0].org_unit_id,
                period=period,
                event_uid=None,
                calculation_run_id=run.id if run else None,
                programme_id=mpdsr.id,
                extra=json.dumps([str(sig[0]), str(sig[1]), str(sig[2])]),
                explanation=RULES["POSSIBLE_DUPLICATE_EVENT"]["explanation"],
                evidence={"count": len(group), "event_type": sig[2]},
            )
        )
    return flags


def _scan_mappings(session, org_unit, period, run, enabled) -> list[DataQualityFlag | None]:
    flags: list[DataQualityFlag | None] = []
    mapping_query = select(SourceMapping).where(SourceMapping.enabled.is_(True))
    if run is not None and run.programme_id is not None:
        mapping_query = mapping_query.where(SourceMapping.programme_id == run.programme_id)
    mappings = list(session.scalars(mapping_query).all())
    if not mappings:
        flags.append(
            _upsert_flag(
                session,
                rule="MAPPING_MISSING",
                enabled=enabled,
                org_unit_id=org_unit.id,
                period=period,
                programme_id=run.programme_id if run else None,
                calculation_run_id=run.id if run else None,
                explanation=RULES["MAPPING_MISSING"]["explanation"],
                evidence={"enabled_mappings": 0},
            )
        )
        return flags
    seen: dict[tuple, str] = {}
    for row in mappings:
        key = (row.programme_id, row.mapping_version, row.dhis2_item_uid, row.category_option_combo_uid or "")
        previous = seen.get(key)
        if previous and previous != row.internal_source_key:
            flags.append(
                _upsert_flag(
                    session,
                    rule="MAPPING_AMBIGUOUS",
                    enabled=enabled,
                    org_unit_id=org_unit.id,
                    period=period,
                    source_key=row.internal_source_key,
                    programme_id=row.programme_id,
                    calculation_run_id=run.id if run else None,
                    explanation=RULES["MAPPING_AMBIGUOUS"]["explanation"],
                    evidence={"mapping_version": row.mapping_version},
                )
            )
        elif row.dhis2_item_uid:
            seen[key] = row.internal_source_key
        current_uid = row.dhis2_item_uid
        raws = session.scalars(
            select(RawAggregateValue).where(
                RawAggregateValue.programme_id == row.programme_id,
                RawAggregateValue.internal_source_key == row.internal_source_key,
                RawAggregateValue.period == period,
                RawAggregateValue.is_current.is_(True),
            )
        ).all()
        for raw in raws:
            if raw.dhis2_item_uid and current_uid and raw.dhis2_item_uid != current_uid:
                flags.append(
                    _upsert_flag(
                        session,
                        rule="METADATA_DRIFT",
                        enabled=enabled,
                        org_unit_id=raw.org_unit_id,
                        period=period,
                        source_key=row.internal_source_key,
                        programme_id=row.programme_id,
                        calculation_run_id=run.id if run else None,
                        explanation=RULES["METADATA_DRIFT"]["explanation"],
                        evidence={"mapped_uid_changed": True},
                    )
                )
    return flags


def _scan_freshness(session, org_unit, period, run, enabled) -> list[DataQualityFlag | None]:
    flags: list[DataQualityFlag | None] = []
    snapshots = list(session.scalars(select(FreshnessSnapshot).order_by(FreshnessSnapshot.connector)).all())
    # Deterministic: the oldest analytics freshness is the one that can be stale.
    analytics_rows = [row for row in snapshots if "event_analytics" in row.connector and row.source_freshness_at]
    analytics = min(analytics_rows, key=lambda row: row.source_freshness_at) if analytics_rows else None
    tracker = next((row for row in snapshots if row.connector == "tracker"), None)
    if analytics and tracker and analytics.source_freshness_at and tracker.source_freshness_at:
        if analytics.source_freshness_at < tracker.source_freshness_at:
            flags.append(
                _upsert_flag(
                    session,
                    rule="STALE_ANALYTICS",
                    enabled=enabled,
                    org_unit_id=org_unit.id,
                    period=period,
                    calculation_run_id=run.id if run else None,
                    explanation=RULES["STALE_ANALYTICS"]["explanation"],
                    evidence={
                        "analytics": analytics.source_freshness_at.isoformat(),
                        "tracker": tracker.source_freshness_at.isoformat(),
                    },
                )
            )
            flags.append(
                _upsert_flag(
                    session,
                    rule="SOURCE_FRESHNESS_MISMATCH",
                    enabled=enabled,
                    org_unit_id=org_unit.id,
                    period=period,
                    calculation_run_id=run.id if run else None,
                    explanation=RULES["SOURCE_FRESHNESS_MISMATCH"]["explanation"],
                    evidence={
                        "lag_seconds": int(
                            (tracker.source_freshness_at - analytics.source_freshness_at).total_seconds()
                        )
                    },
                )
            )
    return flags


def _scan_facility_population(session, org_unit, period, run, enabled) -> list[DataQualityFlag | None]:
    flags: list[DataQualityFlag | None] = []
    units = descendants(session, org_unit, include_self=True)
    ids = [unit.id for unit in units]
    pending = session.scalars(
        select(FacilityPopulationEntry).where(
            FacilityPopulationEntry.org_unit_id.in_(ids),
            FacilityPopulationEntry.approval_status == ApprovalStatus.DRAFT.value,
        )
    ).all()
    for entry in pending:
        flags.append(
            _upsert_flag(
                session,
                rule="FACILITY_POPULATION_PENDING_APPROVAL",
                enabled=enabled,
                org_unit_id=entry.org_unit_id,
                period=period,
                calculation_run_id=run.id if run else None,
                extra=str(entry.id),
                explanation=RULES["FACILITY_POPULATION_PENDING_APPROVAL"]["explanation"],
                evidence={"year": entry.year, "status": entry.approval_status},
            )
        )
    return flags


def _scan_parent_child(session, org_unit, period, run, enabled) -> list[DataQualityFlag | None]:
    flags: list[DataQualityFlag | None] = []
    units = descendants(session, org_unit, include_self=True)
    ids = [unit.id for unit in units]
    query = select(RawAggregateValue).where(
        RawAggregateValue.org_unit_id.in_(ids),
        RawAggregateValue.period == period,
        RawAggregateValue.is_current.is_(True),
    )
    if run is not None and run.programme_id is not None:
        query = query.where(RawAggregateValue.programme_id == run.programme_id)
    rows = session.scalars(query).all()
    by_key: dict[str, list[RawAggregateValue]] = {}
    unit_by_id = {unit.id: unit for unit in units}
    for row in rows:
        if row.internal_source_key:
            by_key.setdefault(row.internal_source_key, []).append(row)
    for key, group in by_key.items():
        # Compare approved aggregation classes, not level_type text: districts and cities
        # are peers. Overlapping units (one inside another) are also a parent/child mix.
        grouped_units = [unit_by_id[row.org_unit_id] for row in group if row.org_unit_id in unit_by_id]
        levels = {
            (cls.value if (cls := aggregation_class(unit.level_type)) else unit.level_type)
            for unit in grouped_units
        }
        if len(levels) > 1 or has_overlapping_units(grouped_units):
            flags.append(
                _upsert_flag(
                    session,
                    rule="PARENT_CHILD_RECONCILIATION",
                    enabled=enabled,
                    org_unit_id=org_unit.id,
                    period=period,
                    source_key=key,
                    programme_id=next((row.programme_id for row in group if row.programme_id), None),
                    calculation_run_id=run.id if run else None,
                    explanation=RULES["PARENT_CHILD_RECONCILIATION"]["explanation"],
                    evidence={"levels": sorted(levels)},
                )
            )
    return flags


def _scan_stale_and_spike(session, org_unit, period, run, enabled) -> list[DataQualityFlag | None]:
    flags: list[DataQualityFlag | None] = []
    settings = get_settings()
    stale_rule = enabled.get("STALE_REPORTING")
    spike_rule = enabled.get("ANOMALOUS_SPIKE_DROP")
    units = descendants(session, org_unit, include_self=True)
    ids = [unit.id for unit in units]
    query = select(RawAggregateValue).where(
        RawAggregateValue.org_unit_id.in_(ids),
        RawAggregateValue.period == period,
        RawAggregateValue.is_current.is_(True),
    )
    if run is not None and run.programme_id is not None:
        query = query.where(RawAggregateValue.programme_id == run.programme_id)
    rows = session.scalars(query).all()
    now = datetime.now(UTC)
    for row in rows:
        if stale_rule and row.extracted_at:
            extracted = row.extracted_at
            if extracted.tzinfo is None:
                extracted = extracted.replace(tzinfo=UTC)
            age_hours = (now - extracted).total_seconds() / 3600
            if age_hours > settings.dhis2_stale_hours:
                flags.append(
                    _upsert_flag(
                        session,
                        rule="STALE_REPORTING",
                        enabled=enabled,
                        org_unit_id=row.org_unit_id,
                        period=period,
                        source_key=row.internal_source_key,
                        programme_id=row.programme_id,
                        calculation_run_id=run.id if run else None,
                        extra="age",
                        explanation=RULES["STALE_REPORTING"]["explanation"],
                        evidence={"age_hours": round(age_hours, 1)},
                    )
                )
        if spike_rule and row.value is not None and row.internal_source_key:
            config = spike_rule.config or {}
            ratio = float(config.get("ratio") or 3.0)
            prior = session.scalars(
                select(RawAggregateValue).where(
                    RawAggregateValue.org_unit_id == row.org_unit_id,
                    RawAggregateValue.internal_source_key == row.internal_source_key,
                    RawAggregateValue.is_current.is_(True),
                    RawAggregateValue.period != period,
                    RawAggregateValue.value.is_not(None),
                )
            ).all()
            for previous in prior:
                old = float(previous.value)
                new = float(row.value)
                if old > 0 and (new / old >= ratio or old / max(new, 0.0001) >= ratio):
                    flags.append(
                        _upsert_flag(
                            session,
                            rule="ANOMALOUS_SPIKE_DROP",
                            enabled=enabled,
                            org_unit_id=row.org_unit_id,
                            period=period,
                            source_key=row.internal_source_key,
                            programme_id=row.programme_id,
                            calculation_run_id=run.id if run else None,
                            extra=previous.period,
                            explanation=RULES["ANOMALOUS_SPIKE_DROP"]["explanation"],
                            evidence={"reference_period": previous.period, "ratio": ratio},
                        )
                    )
                    break
    return flags


def seed_quality_rules(session: Session) -> None:
    existing = {row.code: row for row in session.scalars(select(QualityRule)).all()}
    for item in QUALITY_RULE_CATALOG:
        if item["code"] in existing:
            continue
        config = None
        if item["code"] == "UNEXPECTED_ZERO":
            config = {"require_prior_nonzero": True}
        if item["code"] == "ANOMALOUS_SPIKE_DROP":
            config = {"ratio": 3.0}
        session.add(
            QualityRule(
                code=item["code"],
                category=item["category"],
                severity=item["severity"],
                explanation=item["explanation"],
                rule_version="v1",
                enabled=True,
                config=config,
            )
        )

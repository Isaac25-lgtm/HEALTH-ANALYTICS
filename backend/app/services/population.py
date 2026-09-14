from __future__ import annotations

import zlib
from dataclasses import dataclass
from datetime import UTC, date, datetime
from math import isfinite
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain.enums import (
    ActionPermission,
    AggregationClass,
    ApprovalStatus,
    OrgUnitLevel,
    PeriodRuleScope,
    PopulationAggregationPolicy,
    PopulationType,
    UnavailableReason,
)
from app.domain.periods import PeriodSpec, parse_period
from app.models import (
    FacilityPopulationEntry,
    OrgUnit,
    PeriodPopulationRule,
    PopulationValue,
    PopulationVersion,
    User,
)
from app.services.audit import write_audit
from app.services.authorization import AuthorizationError, require_action, require_org_unit_access
from app.services.geography import descendant_classes_below, descendants, top_units_of_class

# Period kinds that are sub-periods or keys of a financial year, and those that are
# calendar-year based. A rule governs only the kinds it lists explicitly.
FINANCIAL_YEAR_KINDS = {"fy", "fy_quarter", "month", "quarter", "half"}
CALENDAR_YEAR_KINDS = {"year", "month", "quarter", "half"}
DEFAULT_APPLIES_TO = {
    PeriodRuleScope.FINANCIAL_YEAR.value: ["fy"],
    PeriodRuleScope.CALENDAR_YEAR.value: ["year"],
}


@dataclass(frozen=True)
class PopulationResolution:
    status: str
    population: float | None
    year: int | None
    version_id: UUID | None
    version_code: str | None
    source: str | None
    policy: str
    reason: str | None
    used_facility_entry_id: UUID | None = None
    selection_reason: str | None = None
    approval_status: str | None = None
    population_type: str | None = None
    reason_code: str | None = None
    rule_id: UUID | None = None
    aggregation_level: str | None = None
    child_unit_ids: tuple[UUID, ...] = ()


@dataclass(frozen=True)
class PopulationYearResolution:
    year: int | None
    rule_id: UUID | None
    reason_code: str | None
    reason: str | None


def _rule_applies(rule: PeriodPopulationRule, scope: str, kind: str) -> bool:
    if (rule.scope_kind or PeriodRuleScope.FINANCIAL_YEAR.value) != scope:
        return False
    if rule.approval_status != ApprovalStatus.APPROVED.value:
        return False
    kinds = rule.applies_to_period_kinds or DEFAULT_APPLIES_TO.get(scope, [])
    return kind in kinds


def _approved_rule(
    session: Session, scope: str, key: str, kind: str, programme_id: UUID | None
) -> PeriodPopulationRule | None:
    rows = session.scalars(
        select(PeriodPopulationRule).where(PeriodPopulationRule.financial_year_key == key)
    ).all()
    applicable = [row for row in rows if _rule_applies(row, scope, kind)]
    if programme_id is not None:
        specific = [row for row in applicable if row.programme_id == programme_id]
        if specific:
            return specific[0]
    general = [row for row in applicable if row.programme_id is None]
    return general[0] if general else None


def resolve_population_year_rule(
    session: Session, period_key: str, programme_id: UUID | None = None
) -> PopulationYearResolution:
    """Resolve the population year only from an approved rule covering this period kind.

    No year is assumed. Programme-specific rules take precedence over general rules;
    another programme's rule is never used.
    """
    spec = parse_period(period_key)
    candidates: list[tuple[str, str]] = []
    fy_key = spec.key if spec.kind == "fy" else spec.parent_fy
    if spec.kind in FINANCIAL_YEAR_KINDS and fy_key:
        candidates.append((PeriodRuleScope.FINANCIAL_YEAR.value, fy_key))
    if spec.kind in CALENDAR_YEAR_KINDS:
        candidates.append((PeriodRuleScope.CALENDAR_YEAR.value, str(spec.start.year)))
    matches = [
        rule
        for scope, key in candidates
        if (rule := _approved_rule(session, scope, key, spec.kind, programme_id)) is not None
    ]
    if not matches:
        return PopulationYearResolution(
            None,
            None,
            UnavailableReason.POPULATION_RULE_MISSING.value,
            f"No approved period-population rule covers {spec.kind} period {spec.key}.",
        )
    years = {rule.population_year for rule in matches}
    if len(years) > 1:
        return PopulationYearResolution(
            None,
            None,
            UnavailableReason.POPULATION_RULE_MISSING.value,
            f"Approved period-population rules conflict for {spec.kind} period {spec.key}.",
        )
    return PopulationYearResolution(matches[0].population_year, matches[0].id, None, None)


def resolve_population_year(session: Session, period_key: str, programme_id: UUID | None = None) -> int | None:
    return resolve_population_year_rule(session, period_key, programme_id).year


def period_fraction(period_key: str) -> float:
    return parse_period(period_key).fraction_of_year


def period_target(annual_population: float, coefficient: float, period_key: str) -> float:
    return annual_population * coefficient * period_fraction(period_key)


def resolve_population(
    session: Session,
    org_unit: OrgUnit,
    *,
    period_key: str,
    version: PopulationVersion | None = None,
    programme_id: UUID | None = None,
    policy: str = PopulationAggregationPolicy.DIRECT_OR_COMPLETE_CHILDREN.value,
) -> PopulationResolution:
    year_rule = resolve_population_year_rule(session, period_key, programme_id)
    year = year_rule.year
    if year is None:
        return PopulationResolution(
            status="unavailable",
            population=None,
            year=None,
            version_id=None,
            version_code=None,
            source=None,
            policy=policy,
            reason=year_rule.reason,
            selection_reason="population_rule_missing",
            reason_code=year_rule.reason_code,
        )
    as_of = parse_period(period_key).start
    if org_unit.level_type == OrgUnitLevel.FACILITY.value:
        entry = _approved_facility_entry(session, org_unit.id, year)
        if entry is not None:
            return PopulationResolution(
                status="ok",
                population=float(entry.population),
                year=year,
                version_id=None,
                version_code=None,
                source=entry.source_name,
                policy=policy,
                reason="Approved facility catchment entry.",
                used_facility_entry_id=entry.id,
                selection_reason="facility_entry_current_approved",
                approval_status=entry.approval_status,
                population_type=entry.population_type,
                rule_id=year_rule.rule_id,
                aggregation_level=AggregationClass.FACILITY.value,
            )
        return PopulationResolution(
            status="unavailable",
            population=None,
            year=year,
            version_id=None,
            version_code=None,
            source=None,
            policy=policy,
            reason="Facility catchment population is unavailable.",
            selection_reason="no_approved_facility_entry",
            reason_code=UnavailableReason.POPULATION_UNAVAILABLE.value,
            rule_id=year_rule.rule_id,
        )

    if version is not None:
        if version.approval_status != ApprovalStatus.APPROVED.value:
            chosen, selection_reason = None, "The caller-supplied population version is not approved."
        elif not _version_covers_date(version, as_of):
            chosen, selection_reason = None, "The caller-supplied population version is not valid for the period."
        elif not _version_covers_geography(session, version, org_unit, year):
            chosen, selection_reason = None, "The caller-supplied population version does not cover the year/geography."
        else:
            chosen, selection_reason = version, "caller_supplied_approved_version"
    else:
        chosen, selection_reason = _select_approved_version(session, org_unit, year, as_of)
    if chosen is None:
        return PopulationResolution(
            status="unavailable",
            population=None,
            year=year,
            version_id=None,
            version_code=None,
            source=None,
            policy=policy,
            reason="No approved population version covers this year and geography.",
            selection_reason=selection_reason,
            reason_code=UnavailableReason.POPULATION_UNAVAILABLE.value,
            rule_id=year_rule.rule_id,
        )
    direct = _direct_value(session, chosen.id, org_unit.id, year)
    if direct is not None:
        return PopulationResolution(
            status="ok",
            population=float(direct.population),
            year=year,
            version_id=chosen.id,
            version_code=chosen.code,
            source=chosen.source_name,
            policy="direct",
            reason=None,
            selection_reason=selection_reason,
            approval_status=chosen.approval_status,
            population_type=chosen.population_type,
            rule_id=year_rule.rule_id,
        )
    cohort = _complete_version_class_sum(session, org_unit, chosen.id, year)
    if cohort is not None:
        total, level, unit_ids = cohort
        return PopulationResolution(
            status="ok",
            population=total,
            year=year,
            version_id=chosen.id,
            version_code=chosen.code,
            source=chosen.source_name,
            policy="children",
            reason=(
                f"Summed the complete {level} cohort from the approved population version. "
                "No parent value and no facility catchment entry was mixed."
            ),
            selection_reason=selection_reason,
            approval_status=chosen.approval_status,
            population_type=chosen.population_type,
            rule_id=year_rule.rule_id,
            aggregation_level=level,
            child_unit_ids=tuple(unit_ids),
        )
    return PopulationResolution(
        status="unavailable",
        population=None,
        year=year,
        version_id=chosen.id,
        version_code=chosen.code,
        source=None,
        policy=policy,
        reason="Population is unavailable without mixing parent and descendant values.",
        selection_reason=selection_reason,
        approval_status=chosen.approval_status,
        population_type=chosen.population_type,
        reason_code=UnavailableReason.POPULATION_UNAVAILABLE.value,
        rule_id=year_rule.rule_id,
    )


def _validate_entry_inputs(*, year: int, population: float, source_name: str, reason: str | None) -> None:
    settings = get_settings()
    if not isfinite(population) or population <= 0:
        raise AuthorizationError("invalid_input", "Population must be a finite number greater than zero.")
    if year < settings.population_year_min or year > settings.population_year_max:
        raise AuthorizationError("invalid_input", "Population year is outside the configured range.")
    if not source_name.strip() or len(source_name) > 255:
        raise AuthorizationError("invalid_input", "Source name is required and must be at most 255 characters.")
    if reason is not None and len(reason) > 500:
        raise AuthorizationError("invalid_input", "Reason must be at most 500 characters.")


def _validate_population_type(population_type: str) -> None:
    if population_type not in {item.value for item in PopulationType}:
        raise AuthorizationError("invalid_input", "Population type is not recognised.")


def import_population_version(
    session: Session,
    user: User,
    *,
    code: str,
    name: str,
    source_name: str,
    source_document: str | None,
    population_type: str,
    valid_from: date | None,
    valid_to: date | None,
    notes: str | None,
    rows: list[dict],
) -> PopulationVersion:
    require_action(session, user, ActionPermission.EDIT_POPULATION)
    _validate_population_type(population_type)
    code = code.strip()
    name = name.strip()
    source_name = source_name.strip()
    if not code or len(code) > 80 or not name or len(name) > 255:
        raise AuthorizationError("invalid_input", "Population version code and name are required.")
    if not source_name or len(source_name) > 255:
        raise AuthorizationError("invalid_input", "Population source is required.")
    if valid_from and valid_to and valid_from > valid_to:
        raise AuthorizationError("invalid_input", "valid_from cannot be after valid_to.")
    if session.scalar(select(PopulationVersion).where(PopulationVersion.code == code)) is not None:
        raise AuthorizationError("invalid_input", "Population version code already exists.")
    if not rows:
        raise AuthorizationError("invalid_input", "At least one population row is required.")
    if len(rows) > 10_000:
        raise AuthorizationError("invalid_input", "A population import is limited to 10,000 rows.")

    normalised: list[tuple[OrgUnit, int, float]] = []
    seen: set[tuple[UUID, int]] = set()
    for item in rows:
        org_code = str(item.get("org_unit_code") or "").strip()
        org_unit = session.scalar(select(OrgUnit).where(OrgUnit.code == org_code))
        if org_unit is None or not org_unit.active:
            raise AuthorizationError("invalid_input", f"Unknown active organisation-unit code: {org_code}")
        require_org_unit_access(session, user, org_unit.id)
        year = int(item["year"])
        population = float(item["population"])
        _validate_entry_inputs(year=year, population=population, source_name=source_name, reason=None)
        key = (org_unit.id, year)
        if key in seen:
            raise AuthorizationError(
                "invalid_input", f"Duplicate population row for {org_code} and {year}."
            )
        seen.add(key)
        normalised.append((org_unit, year, population))

    version = PopulationVersion(
        code=code,
        name=name,
        source_name=source_name,
        source_document=source_document,
        population_type=population_type,
        approval_status=ApprovalStatus.DRAFT.value,
        valid_from=valid_from,
        valid_to=valid_to,
        notes=notes,
        imported_by_user_id=user.id,
    )
    session.add(version)
    session.flush()
    session.add_all(
        [
            PopulationValue(
                version_id=version.id,
                org_unit_id=org_unit.id,
                year=year,
                population=population,
            )
            for org_unit, year, population in normalised
        ]
    )
    write_audit(
        session,
        actor_user_id=user.id,
        action="population_version_imported",
        resource_type="population_version",
        resource_id=str(version.id),
        after={"code": code, "rows": len(normalised), "status": ApprovalStatus.DRAFT.value},
        commit=False,
    )
    session.flush()
    return version


def approve_population_version(
    session: Session,
    user: User,
    version_id: UUID,
    *,
    reason: str | None = None,
) -> PopulationVersion:
    require_action(session, user, ActionPermission.APPROVE_POPULATION)
    version = session.scalar(
        select(PopulationVersion).where(PopulationVersion.id == version_id).with_for_update()
    )
    if version is None:
        raise AuthorizationError("not_found", "Population version not found.")
    if version.approval_status != ApprovalStatus.DRAFT.value:
        raise AuthorizationError("invalid_input", "Only draft population versions can be approved.")
    if version.imported_by_user_id == user.id and not user.is_system_admin:
        raise AuthorizationError("forbidden_action", "The importing user cannot self-approve this version.")
    if session.scalar(
        select(PopulationValue.id).where(PopulationValue.version_id == version.id).limit(1)
    ) is None:
        raise AuthorizationError("invalid_input", "A population version without values cannot be approved.")
    version.approval_status = ApprovalStatus.APPROVED.value
    write_audit(
        session,
        actor_user_id=user.id,
        action="population_version_approved",
        resource_type="population_version",
        resource_id=str(version.id),
        after={"code": version.code, "status": version.approval_status},
        reason=reason,
        commit=False,
    )
    session.flush()
    return version


def reject_population_version(
    session: Session,
    user: User,
    version_id: UUID,
    *,
    reason: str | None = None,
) -> PopulationVersion:
    require_action(session, user, ActionPermission.APPROVE_POPULATION)
    version = session.scalar(
        select(PopulationVersion).where(PopulationVersion.id == version_id).with_for_update()
    )
    if version is None:
        raise AuthorizationError("not_found", "Population version not found.")
    if version.approval_status != ApprovalStatus.DRAFT.value:
        raise AuthorizationError("invalid_input", "Only draft population versions can be rejected.")
    version.approval_status = ApprovalStatus.REJECTED.value
    write_audit(
        session,
        actor_user_id=user.id,
        action="population_version_rejected",
        resource_type="population_version",
        resource_id=str(version.id),
        after={"code": version.code, "status": version.approval_status},
        reason=reason,
        commit=False,
    )
    session.flush()
    return version


def enter_facility_population(
    session: Session,
    user: User,
    *,
    org_unit_id: UUID,
    year: int,
    population: float,
    source_name: str,
    population_type: str,
    reason: str | None,
    notes: str | None = None,
) -> FacilityPopulationEntry:
    require_action(session, user, ActionPermission.EDIT_POPULATION)
    org_unit = require_org_unit_access(session, user, org_unit_id)
    if org_unit.level_type != OrgUnitLevel.FACILITY.value:
        raise AuthorizationError("invalid_geography", "Catchment population entry is limited to facilities.")
    _validate_entry_inputs(year=year, population=population, source_name=source_name, reason=reason)
    _validate_population_type(population_type)
    entry = FacilityPopulationEntry(
        org_unit_id=org_unit.id,
        year=year,
        population=population,
        source_name=source_name.strip(),
        population_type=population_type or PopulationType.FACILITY_CATCHMENT_ESTIMATE.value,
        approval_status=ApprovalStatus.DRAFT.value,
        notes=notes,
        reason=reason,
        entered_by_user_id=user.id,
        is_current_approved=False,
    )
    session.add(entry)
    session.flush()
    return entry


def _advisory_lock_facility_year(session: Session, org_unit_id: UUID, year: int) -> None:
    bind = session.get_bind()
    if bind is None or bind.dialect.name != "postgresql":
        return
    key = zlib.crc32(f"{org_unit_id}:{year}".encode()) & 0x7FFFFFFF
    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


def approve_facility_population(
    session: Session,
    user: User,
    entry_id: UUID,
    *,
    reason: str | None = None,
) -> FacilityPopulationEntry:
    require_action(session, user, ActionPermission.APPROVE_POPULATION)
    entry = session.scalar(
        select(FacilityPopulationEntry).where(FacilityPopulationEntry.id == entry_id).with_for_update()
    )
    if entry is None:
        raise AuthorizationError("not_found", "Facility population entry not found.")
    _advisory_lock_facility_year(session, entry.org_unit_id, entry.year)
    require_org_unit_access(session, user, entry.org_unit_id)
    if entry.approval_status != ApprovalStatus.DRAFT.value:
        raise AuthorizationError("invalid_input", "Only draft facility population entries can be approved.")
    if entry.entered_by_user_id == user.id and not user.is_system_admin:
        raise AuthorizationError(
            "forbidden_action",
            "The entering user cannot self-approve this catchment population.",
        )
    prior = session.scalar(
        select(FacilityPopulationEntry)
        .where(
            FacilityPopulationEntry.org_unit_id == entry.org_unit_id,
            FacilityPopulationEntry.year == entry.year,
            FacilityPopulationEntry.is_current_approved.is_(True),
            FacilityPopulationEntry.approval_status == ApprovalStatus.APPROVED.value,
        )
        .order_by(FacilityPopulationEntry.approved_at.desc())
        .with_for_update()
    )
    before = None
    if prior is not None and prior.id != entry.id:
        before = {"id": str(prior.id), "population": float(prior.population), "status": prior.approval_status}
        prior.approval_status = ApprovalStatus.SUPERSEDED.value
        prior.is_current_approved = False
        prior.superseded_by_id = entry.id
        session.flush()
    now = datetime.now(UTC)
    entry.approval_status = ApprovalStatus.APPROVED.value
    entry.is_current_approved = True
    entry.approved_by_user_id = user.id
    entry.approved_at = now
    if reason:
        entry.reason = reason
    write_audit(
        session,
        actor_user_id=user.id,
        action="facility_population_approved",
        resource_type="facility_population_entry",
        resource_id=str(entry.id),
        before=before,
        after={
            "id": str(entry.id),
            "population": float(entry.population),
            "year": entry.year,
            "superseded_id": str(prior.id) if prior is not None else None,
        },
        reason=reason,
        commit=False,
    )
    session.flush()
    return entry


def reject_facility_population(
    session: Session,
    user: User,
    entry_id: UUID,
    *,
    reason: str | None = None,
) -> FacilityPopulationEntry:
    require_action(session, user, ActionPermission.APPROVE_POPULATION)
    entry = session.get(FacilityPopulationEntry, entry_id)
    if entry is None:
        raise AuthorizationError("not_found", "Facility population entry not found.")
    require_org_unit_access(session, user, entry.org_unit_id)
    if entry.approval_status != ApprovalStatus.DRAFT.value:
        raise AuthorizationError("invalid_input", "Only draft facility population entries can be rejected.")
    entry.approval_status = ApprovalStatus.REJECTED.value
    entry.is_current_approved = False
    entry.rejected_by_user_id = user.id
    entry.rejected_at = datetime.now(UTC)
    entry.rejection_reason = reason
    write_audit(
        session,
        actor_user_id=user.id,
        action="facility_population_rejected",
        resource_type="facility_population_entry",
        resource_id=str(entry.id),
        after={"id": str(entry.id), "status": entry.approval_status},
        reason=reason,
        commit=False,
    )
    session.flush()
    return entry


def _version_covers_date(version: PopulationVersion, as_of: date) -> bool:
    if version.valid_from and as_of < version.valid_from:
        return False
    if version.valid_to and as_of > version.valid_to:
        return False
    return True


def _version_covers_geography(session: Session, version: PopulationVersion, org_unit: OrgUnit, year: int) -> bool:
    if _direct_value(session, version.id, org_unit.id, year) is not None:
        return True
    return _complete_version_class_sum(session, org_unit, version.id, year) is not None


def _select_approved_version(
    session: Session, org_unit: OrgUnit, year: int, as_of: date
) -> tuple[PopulationVersion | None, str]:
    rows = list(
        session.scalars(
            select(PopulationVersion).where(PopulationVersion.approval_status == ApprovalStatus.APPROVED.value)
        ).all()
    )
    covering = [
        row
        for row in rows
        if _version_covers_date(row, as_of) and _version_covers_geography(session, row, org_unit, year)
    ]
    if not covering:
        return None, "No approved version is valid for the requested date and covers the year/geography."
    covering.sort(
        key=lambda row: (
            row.valid_from or date.min,
            row.created_at or datetime.min.replace(tzinfo=UTC),
            row.code,
        ),
        reverse=True,
    )
    chosen = covering[0]
    return (
        chosen,
        "Selected approved version covering year/geography by latest valid_from, then created_at, then code.",
    )


def _direct_value(session: Session, version_id: UUID, org_unit_id: UUID, year: int) -> PopulationValue | None:
    return session.scalar(
        select(PopulationValue).where(
            PopulationValue.version_id == version_id,
            PopulationValue.org_unit_id == org_unit_id,
            PopulationValue.year == year,
        )
    )


def _approved_facility_entry(session: Session, org_unit_id: UUID, year: int) -> FacilityPopulationEntry | None:
    return session.scalar(
        select(FacilityPopulationEntry)
        .where(
            FacilityPopulationEntry.org_unit_id == org_unit_id,
            FacilityPopulationEntry.year == year,
            FacilityPopulationEntry.is_current_approved.is_(True),
            FacilityPopulationEntry.approval_status == ApprovalStatus.APPROVED.value,
        )
        .order_by(FacilityPopulationEntry.approved_at.desc())
    )


def _complete_version_class_sum(
    session: Session, parent: OrgUnit, version_id: UUID, year: int
) -> tuple[float, str, list[UUID]] | None:
    """Sum one complete, non-overlapping administrative cohort from a population version.

    Only approved-version values count. Facility catchment entries and facility-level
    values are never summed into a parent: catchment populations stay facility-only.
    The nearest complete class below the parent is used; classes are never mixed.
    """
    units = descendants(session, parent, include_self=False)
    if not units:
        return None
    values = {
        row.org_unit_id: row
        for row in session.scalars(
            select(PopulationValue).where(
                PopulationValue.version_id == version_id,
                PopulationValue.year == year,
                PopulationValue.org_unit_id.in_([unit.id for unit in units]),
            )
        ).all()
    }
    if not values:
        return None
    for cls in descendant_classes_below(parent, units):
        if cls == AggregationClass.FACILITY:
            continue
        cohort = top_units_of_class(units, cls)
        if cohort and all(unit.id in values for unit in cohort):
            total = sum(float(values[unit.id].population) for unit in cohort)
            return total, cls.value, sorted((unit.id for unit in cohort), key=str)
    return None


def now_utc() -> datetime:
    return datetime.now(UTC)


def parse_period_spec(period_key: str) -> PeriodSpec:
    return parse_period(period_key)

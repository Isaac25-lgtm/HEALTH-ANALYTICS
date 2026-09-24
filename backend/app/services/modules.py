from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain.enums import ActionPermission, AggregationClass, OrgUnitLevel, ProgrammeCode
from app.domain.interpretation import interpret_change
from app.domain.modules import MODULE_INDICATORS, MODULE_PROGRAMME
from app.domain.mpdsr_cause_taxonomy import CauseTaxonomy, current_cause_taxonomy
from app.domain.periods import parse_period, previous_period, trend_window
from app.models import (
    CalculatedValue,
    CalculationRun,
    DataQualityFlag,
    Indicator,
    IndicatorVersion,
    OrgUnit,
    Programme,
    RawAggregateValue,
    User,
)
from app.services.authorization import (
    AuthorizationError,
    can_access_org_unit,
    require_action,
    require_org_unit_access,
    require_programme_access,
)
from app.services.calculation import clear_calculation_batch, prepare_calculation_batch, run_calculation
from app.services.geography import descendants, top_units_of_class
from app.services.mpdsr import is_completed
from app.services.mpdsr_events import scoped_mpdsr_events
from app.services.quality import scan_quality


def _children(session: Session, org_unit: OrgUnit) -> list[OrgUnit]:
    return list(
        session.scalars(
            select(OrgUnit)
            .where(OrgUnit.parent_id == org_unit.id, OrgUnit.active.is_(True))
            .order_by(OrgUnit.name)
        ).all()
    )


FORMULA_UNAVAILABLE_TEXT = (
    "No formula version is valid for this period's effective date, so the indicator is not calculated."
)


def _selection_map(run: CalculationRun) -> dict[str, dict]:
    config = run.config_snapshot or {}
    return {
        item["indicator_code"]: item
        for item in config.get("formula_version_selection") or []
        if item.get("indicator_code")
    }


def _indicator_payload(
    session: Session,
    code: str,
    row: CalculatedValue | None,
    selection: dict[str, dict],
) -> dict:
    """Serialise one indicator cell, keeping identity and the formula-version decision."""
    payload = _serialize_value(session, row)
    decision = selection.get(code) or {}
    if row is None:
        indicator = session.scalar(select(Indicator).where(Indicator.code == code))
        payload["indicator_code"] = code
        payload["name"] = indicator.name if indicator else None
        if decision.get("status") == "unavailable":
            payload["reason_code"] = decision.get("reason_code")
            payload["blue_reason"] = FORMULA_UNAVAILABLE_TEXT
    if decision:
        payload["formula_version_rule"] = decision.get("rule")
        payload["formula_version_effective_date"] = decision.get("effective_date")
    return payload


def _value_map(session: Session, run: CalculationRun) -> dict[str, CalculatedValue]:
    rows = session.scalars(select(CalculatedValue).where(CalculatedValue.calculation_run_id == run.id)).all()
    mapped: dict[str, CalculatedValue] = {}
    for row in rows:
        version = session.get(IndicatorVersion, row.indicator_version_id)
        indicator = session.get(Indicator, version.indicator_id) if version else None
        if indicator is not None:
            mapped[indicator.code] = row
    return mapped


def _thresholds(version: IndicatorVersion | None, mode: str) -> dict | None:
    if version is None:
        return None
    if mode == "neutral_count":
        return {"state": "neutral_count", "text": "Count column. Not classified."}
    if mode == "unclassified":
        return {"state": "no_approved_threshold", "text": "No approved threshold (TBD). Not classified."}
    parts = [
        f"Green {version.green_band}" if version.green_band else None,
        f"Yellow {version.yellow_band}" if version.yellow_band else None,
        f"Red {version.red_band}" if version.red_band else None,
        f"BLUE: {version.blue_rule}" if version.blue_rule else None,
    ]
    return {
        "state": "approved",
        "target": version.target,
        "green": version.green_band,
        "yellow": version.yellow_band,
        "red": version.red_band,
        "blue_rule": version.blue_rule,
        "text": "; ".join(part for part in parts if part) or f"Classification mode {mode}",
    }


def _serialize_value(session: Session, row: CalculatedValue | None) -> dict:
    if row is None:
        return {
            "raw_value": None,
            "display_value": None,
            "numerator": None,
            "denominator": None,
            "unit": None,
            "status": "n_a",
            "performance_status": "n_a",
            "quality_status": None,
            "blue_reason": "No calculated value is available.",
        }
    version = session.get(IndicatorVersion, row.indicator_version_id)
    indicator = session.get(Indicator, version.indicator_id) if version else None
    spec = (version.classification_spec or {}) if version else {}
    mode = spec.get("mode") or "unclassified"
    return {
        "indicator_code": indicator.code if indicator else None,
        "name": indicator.name if indicator else None,
        "raw_value": float(row.raw_value) if row.raw_value is not None else None,
        "display_value": row.display_value,
        "numerator": float(row.numerator) if row.numerator is not None else None,
        "denominator": float(row.denominator) if row.denominator is not None else None,
        "unit": row.unit,
        "status": row.status,
        "performance_status": row.performance_status,
        "quality_status": row.quality_status,
        "blue_reason": row.blue_reason,
        "reason_code": row.reason_code,
        "missing_components": row.missing_components,
        "aggregation_policy": row.aggregation_policy,
        "aggregation_level": row.aggregation_level,
        "mapping_version": row.mapping_version,
        "source_freshness_at": row.source_freshness_at.isoformat() if row.source_freshness_at else None,
        "population_year": row.population_year,
        "population_version_id": str(row.population_version_id) if row.population_version_id else None,
        "facility_population_entry_id": (
            str(row.facility_population_entry_id) if row.facility_population_entry_id else None
        ),
        "formula_version": version.formula_version if version else None,
        "calculation_run_id": str(row.calculation_run_id),
        "direction": row.direction,
        "classification_mode": mode,
        "desired_range": spec.get("green") if mode == "desired_range" else None,
        "display_precision": row.display_precision,
        "thresholds": _thresholds(version, mode),
        "event_coverage_status": (row.event_coverage or {}).get("status"),
        "denominator_provenance": row.denominator_provenance,
        "period_kind": (row.denominator_provenance or {}).get("period_kind"),
        "population_period_fraction": (row.denominator_provenance or {}).get("period_fraction"),
    }


def _change(current: CalculatedValue | None, previous: CalculatedValue | None) -> dict:
    if current is None or previous is None or current.raw_value is None or previous.raw_value is None:
        return {
            "absolute_change": None,
            "percentage_point_change": None,
            "relative_percent_change": None,
            "change_kind": None,
        }
    absolute = float(current.raw_value) - float(previous.raw_value)
    relative = None
    if float(previous.raw_value) != 0:
        relative = (absolute / float(previous.raw_value)) * 100
    unit = (current.unit or "").lower()
    if unit == "%":
        return {
            "absolute_change": absolute,
            "percentage_point_change": absolute,
            "relative_percent_change": relative,
            "change_kind": "percentage_point",
        }
    return {
        "absolute_change": absolute,
        "percentage_point_change": None,
        "relative_percent_change": relative,
        "change_kind": "absolute",
    }


def _freshness(session: Session, org_unit: OrgUnit, period: str, programme_id: UUID) -> dict:
    units = [unit.id for unit in descendants(session, org_unit, include_self=True)]
    rows = session.scalars(
        select(RawAggregateValue).where(
            RawAggregateValue.org_unit_id.in_(units),
            RawAggregateValue.period == period,
            RawAggregateValue.programme_id == programme_id,
            RawAggregateValue.is_current.is_(True),
        )
    ).all()
    extracted = [row.extracted_at for row in rows if row.extracted_at]
    source = [row.source_freshness_at for row in rows if row.source_freshness_at]
    return {
        "raw_row_count": len(rows),
        "latest_extracted_at": max(extracted).isoformat() if extracted else None,
        "latest_source_freshness_at": max(source).isoformat() if source else None,
        "availability": "available" if rows else "no_source_rows",
    }


def _quality_flags(session: Session, run: CalculationRun) -> list[dict]:
    rows = session.scalars(
        select(DataQualityFlag).where(DataQualityFlag.calculation_run_id == run.id)
    ).all()
    return [
        {
            "id": str(row.id),
            "rule_id": row.rule_id,
            "severity": row.severity,
            "status": row.status,
            "explanation": row.explanation,
        }
        for row in rows
    ]


_BANDED_STATUSES = {"green", "yellow", "red"}


def _continuum_step(value: CalculatedValue | None, *, missing_status: str = "n_a") -> dict:
    """One continuum step as calculated: value, display, unit and status, plus whether an approved
    band classified it. Nothing is re-derived here."""
    status = value.status if value is not None else missing_status
    return {
        "raw_value": float(value.raw_value) if value is not None and value.raw_value is not None else None,
        "display_value": value.display_value if value is not None else None,
        "unit": value.unit if value is not None else "%",
        "status": status,
        "threshold_state": "approved_band" if status in _BANDED_STATUSES else "no_approved_threshold",
    }


def _continuum(current: dict[str, CalculatedValue]) -> dict | None:
    penta1 = current.get("PENTA1_COVERAGE")
    penta3 = current.get("PENTA3_COVERAGE")
    dropout = current.get("PENTA_DROPOUT")
    mv1 = current.get("MV1_COVERAGE")
    mv4 = current.get("MV4_COVERAGE")
    mv_drop = current.get("MV1_MV4_DROPOUT")
    if not any([penta1, penta3, dropout, mv1, mv4, mv_drop]):
        return None
    return {
        "penta_access": _continuum_step(penta1),
        "penta_completion": _continuum_step(penta3),
        "penta_dropout": _continuum_step(dropout, missing_status="unclassified"),
        "malaria_access": _continuum_step(mv1),
        "malaria_completion": _continuum_step(mv4),
        "malaria_dropout": _continuum_step(mv_drop, missing_status="unclassified"),
        "note": (
            "Continuum distinguishes access (first dose) from completion (last dose). "
            "Colours follow the approved EPI bands; a step without an approved band is not classified."
        ),
    }


CAUSE_DISCLOSURE_LEVELS = {
    OrgUnitLevel.COUNTRY.value,
    OrgUnitLevel.REGION.value,
    OrgUnitLevel.SUB_REGION.value,
}


def _structured_cause_categories(payload: dict, taxonomy: CauseTaxonomy) -> list[str]:
    """Only approved taxonomy codes are counted. There is no free-text cause fallback, and a value
    that is not an exact approved code (a label, a narrative, a name) is ignored, not matched."""
    values = payload.get("structured_cause_mentions") or []
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list | tuple):
        return []
    return [item for item in values if taxonomy.contains(item)]


def _mpdsr_extras(
    session: Session,
    org_unit: OrgUnit,
    period: str,
    user: User,
) -> dict:
    cohort = scoped_mpdsr_events(session, org_unit, period)
    try:
        require_action(session, user, ActionPermission.VIEW_MPDSR_EVENTS)
        require_programme_access(session, user, ProgrammeCode.MPDSR.value)
        can_view_events = True
    except AuthorizationError:
        can_view_events = False
    min_cell = get_settings().mpdsr_cause_min_cell_count
    taxonomy = current_cause_taxonomy()
    extras: dict = {
        "structured_cause_mentions": [],
        "cause_chart": "horizontal_bar",
        "cause_note": "Categories may overlap. These are structured cause mentions, not exclusive causes.",
        "active_events": None,
    }
    if org_unit.level_type not in CAUSE_DISCLOSURE_LEVELS:
        extras["cause_disclosure"] = {
            "status": "withheld",
            "reason": "Cause patterns are not presented below regional level without an approved disclosure policy.",
        }
    elif not can_view_events:
        extras["cause_disclosure"] = {
            "status": "withheld",
            "reason": "Cause patterns require MPDSR programme access and MPDSR event permission.",
        }
    elif taxonomy is None:
        extras["cause_disclosure"] = {
            "status": "withheld",
            "reason": "No approved MPDSR cause taxonomy is configured; cause values are not stored or shown.",
        }
    elif min_cell is None or min_cell < 1:
        extras["cause_disclosure"] = {
            "status": "withheld",
            "reason": "No approved small-number suppression rule is configured for MPDSR causes.",
        }
    else:
        mentions: Counter[str] = Counter()
        sources: dict[str, set] = {}
        for event in cohort:
            for category in set(_structured_cause_categories(event.data_values or {}, taxonomy)):
                mentions[category] += 1
                sources.setdefault(category, set()).add(event.org_unit_id)
        # A category is shown only when it meets the approved minimum cell count and its
        # mentions come from more than one reporting unit, so no single facility is exposed.
        shown = [
            {"code": name, "category": taxonomy.label(name), "mentions": count}
            for name, count in sorted(mentions.items(), key=lambda item: (-item[1], item[0]))
            if count >= min_cell and len(sources[name]) > 1
        ]
        extras["structured_cause_mentions"] = shown
        extras["cause_disclosure"] = {
            "status": "disclosed",
            "taxonomy_version": taxonomy.version,
            "level": org_unit.level_type,
            "min_cell_count": min_cell,
            "suppressed_categories": len(mentions) - len(shown),
            "suppression_reasons": ["below_min_cell_count", "single_reporting_unit"],
        }
    if can_view_events:
        extras["active_events"] = {
            "count": sum(1 for event in cohort if not is_completed(event)),
            "label": "Active (not completed)",
        }
    return extras


def evaluate_module(
    session: Session,
    *,
    user: User,
    org_unit_id: UUID,
    period: str,
    module: str,
    comparison_period: str | None = None,
    include_children: bool = True,
    district_cohort: bool = False,
) -> dict:
    """Evaluate one module for a unit.

    ``district_cohort`` additionally evaluates every authorised district/city below the unit, so a
    national or regional screen can map and rank districts, as the reference screens do.
    """
    if module not in MODULE_INDICATORS:
        raise AuthorizationError("invalid_input", "Analytical module is not recognised.")
    programme_code = MODULE_PROGRAMME[module]
    require_action(session, user, ActionPermission.VIEW)
    org_unit = require_org_unit_access(session, user, org_unit_id)
    require_programme_access(session, user, programme_code)
    parse_period(period)
    compare_key = comparison_period or previous_period(period)
    parse_period(compare_key)
    codes = MODULE_INDICATORS[module]
    periods = [period, compare_key, *trend_window(period)]
    prepare_calculation_batch(session, org_unit=org_unit, periods=periods, programme_codes=[programme_code])
    try:
        return _evaluate_module_body(
            session,
            user=user,
            org_unit=org_unit,
            period=period,
            compare_key=compare_key,
            module=module,
            programme_code=programme_code,
            codes=codes,
            include_children=include_children,
            district_cohort=district_cohort,
        )
    finally:
        clear_calculation_batch(session)


def _evaluate_module_body(
    session: Session,
    *,
    user: User,
    org_unit: OrgUnit,
    period: str,
    compare_key: str,
    module: str,
    programme_code: str,
    codes: list[str],
    include_children: bool,
    district_cohort: bool = False,
) -> dict:
    current_run = run_calculation(
        session,
        org_unit=org_unit,
        period=period,
        user=user,
        programme_codes=[programme_code],
        indicator_codes=codes,
    )
    scan_quality(session, org_unit=org_unit, period=period, calculation_run=current_run)
    compare_run = run_calculation(
        session,
        org_unit=org_unit,
        period=compare_key,
        user=user,
        programme_codes=[programme_code],
        indicator_codes=codes,
    )
    current_values = _value_map(session, current_run)
    compare_values = _value_map(session, compare_run)
    current_selection = _selection_map(current_run)
    compare_selection = _selection_map(compare_run)
    indicators = []
    for code in codes:
        current = current_values.get(code)
        previous = compare_values.get(code)
        payload = _indicator_payload(session, code, current, current_selection)
        payload["comparison"] = _indicator_payload(session, code, previous, compare_selection)
        change = _change(current, previous)
        interpretation = interpret_change(
            classification_mode=payload.get("classification_mode"),
            current=payload if current is not None else None,
            previous=payload["comparison"] if previous is not None else None,
            desired_range=payload.get("desired_range"),
            precision=payload.get("display_precision"),
        )
        change["interpretation"] = interpretation["interpretation"]
        change["interpretation_reason"] = interpretation["reason"]
        change["status_transition"] = interpretation["status_transition"]
        payload["change"] = change
        indicators.append(payload)

    trend = []
    for key in trend_window(period):
        run = run_calculation(
            session,
            org_unit=org_unit,
            period=key,
            user=user,
            programme_codes=[programme_code],
            indicator_codes=codes,
        )
        values = _value_map(session, run)
        selection = _selection_map(run)
        trend.append(
            {
                "period": key,
                "calculation_run_id": str(run.id),
                "values": {code: _indicator_payload(session, code, values.get(code), selection) for code in codes},
            }
        )

    def unit_row(child: OrgUnit) -> dict:
        run = run_calculation(
            session,
            org_unit=child,
            period=period,
            user=user,
            programme_codes=[programme_code],
            indicator_codes=codes,
        )
        values = _value_map(session, run)
        selection = _selection_map(run)
        return {
            "org_unit_id": str(child.id),
            "org_unit_code": child.code,
            "org_unit_name": child.name,
            "level_type": child.level_type,
            "calculation_run_id": str(run.id),
            "values": {code: _indicator_payload(session, code, values.get(code), selection) for code in codes},
        }

    comparisons = []
    children: list[OrgUnit] = []
    if include_children:
        children = [child for child in _children(session, org_unit) if can_access_org_unit(session, user, child)]
        comparisons = [unit_row(child) for child in children]

    district_rows: list[dict] = []
    if district_cohort:
        cohort = sorted(
            top_units_of_class(descendants(session, org_unit), AggregationClass.DISTRICT_EQUIVALENT),
            key=lambda unit: unit.name,
        )
        by_id = {row["org_unit_id"]: row for row in comparisons}
        district_rows = [
            by_id.get(str(unit.id)) or unit_row(unit)
            for unit in cohort
            if can_access_org_unit(session, user, unit)
        ]

    result = {
        "module": module,
        "programme": programme_code,
        "org_unit_id": str(org_unit.id),
        "org_unit_code": org_unit.code,
        "org_unit_name": org_unit.name,
        "period": period,
        "comparison_period": compare_key,
        "generated_at": datetime.now(UTC).isoformat(),
        "current_run_id": str(current_run.id),
        "comparison_run_id": str(compare_run.id),
        "freshness": _freshness(
            session,
            org_unit,
            period,
            session.scalar(select(Programme).where(Programme.code == programme_code)).id,
        ),
        "quality_flags": _quality_flags(session, current_run),
        "indicators": indicators,
        "trends": trend,
        "org_unit_comparison": comparisons,
        "district_comparison": district_rows,
        "fixture_label": None,
    }
    if module == "immunization":
        result["continuum"] = _continuum(current_values)
    if module == "mpdsr":
        result["mpdsr"] = _mpdsr_extras(session, org_unit, period, user)
    return result

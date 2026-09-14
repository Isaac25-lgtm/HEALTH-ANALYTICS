from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.domain.enums import ActionPermission, DenominatorType, OrgUnitLevel, ProgrammeCode
from app.domain.indicator_catalog import INDICATOR_CATALOG
from app.domain.interpretation import UNSAFE_RANK_CODES, rank_units
from app.domain.modules import MODULE_INDICATORS, MODULE_PROGRAMME
from app.domain.periods import parse_period
from app.models import OrgUnit, User
from app.services.analysis import persist_snapshot
from app.services.authorization import (
    AuthorizationError,
    can_access_org_unit,
    programme_scope_codes,
    require_action,
    require_org_unit_access,
    user_actions,
)
from app.services.calculation import clear_calculation_batch, prepare_calculation_batch, run_calculation
from app.services.evidence import evidence_package
from app.services.geography import ancestors, descendants
from app.services.geometry import build_map_block, map_feature_collection
from app.services.modules import _indicator_payload, _selection_map, _value_map, evaluate_module
from app.services.population import resolve_population

_CATALOG = {row["code"]: row for row in INDICATOR_CATALOG}

SCREEN_BY_LEVEL = {
    OrgUnitLevel.COUNTRY.value: "national",
    OrgUnitLevel.REGION.value: "regional",
    OrgUnitLevel.SUB_REGION.value: "regional",
    OrgUnitLevel.DISTRICT.value: "district",
    OrgUnitLevel.CITY.value: "district",
    OrgUnitLevel.SUB_COUNTY.value: "sub_county",
    OrgUnitLevel.FACILITY.value: "facility",
}


def _ancestor_of_type(session: Session, org_unit: OrgUnit, level: str) -> OrgUnit | None:
    if org_unit.level_type == level:
        return org_unit
    for item in ancestors(session, org_unit):
        if item.level_type == level:
            return item
    return None


def _summary(unit: OrgUnit | None) -> dict | None:
    if unit is None:
        return None
    return {
        "id": str(unit.id),
        "code": unit.code,
        "name": unit.name,
        "level_type": unit.level_type,
        "parent_id": str(unit.parent_id) if unit.parent_id else None,
        "path": unit.path,
        "ownership": unit.ownership,
        "facility_level": unit.facility_level,
    }


def available_modules(programmes: list[str]) -> list[str]:
    allowed = set(programmes)
    return [module for module, programme in MODULE_PROGRAMME.items() if programme in allowed]


def default_module(programmes: list[str]) -> str:
    modules = available_modules(programmes)
    if not modules:
        raise AuthorizationError("forbidden", "No authorised analytical module is available.")
    return modules[0]


def _insights(module_payload: dict, population: dict) -> list[dict]:
    insights: list[dict] = []
    if population.get("status") == "unavailable":
        insights.append(
            {
                "severity": "info",
                "code": "missing_population",
                "title": "Approved population is unavailable",
                "detail": (
                    population.get("reason")
                    or "Population-derived indicators are non-assessable until an approved denominator exists."
                ),
            }
        )
    for row in module_payload.get("indicators") or []:
        code = row.get("indicator_code")
        status = row.get("quality_status") or row.get("status")
        if row.get("raw_value") is None:
            insights.append(
                {
                    "severity": "info",
                    "code": "unavailable_indicator",
                    "title": f"{row.get('name') or code or 'An indicator'} is unavailable",
                    "detail": row.get("blue_reason") or "A required component is missing or non-assessable.",
                    "indicator_code": code,
                }
            )
            continue
        if status == "blue":
            insights.append(
                {
                    "severity": "quality",
                    "code": "blue_state",
                    "title": f"{row.get('name') or code} is non-assessable",
                    "detail": row.get("blue_reason")
                    or "BLUE indicates a data-quality or definition issue, not high performance.",
                    "indicator_code": code,
                }
            )
        elif status == "red":
            insights.append(
                {
                    "severity": "priority",
                    "code": "below_threshold",
                    "title": f"{row.get('name') or code} is outside the approved performance band",
                    "detail": "This is a calculated status from the approved bands. It does not imply cause or blame.",
                    "indicator_code": code,
                }
            )
        if row.get("raw_value") is not None and (row.get("unit") == "%") and row["raw_value"] > 100:
            insights.append(
                {
                    "severity": "quality",
                    "code": "over_100",
                    "title": f"{row.get('name') or code} exceeds 100%",
                    "detail": "The calculated value was retained. It was not capped.",
                    "indicator_code": code,
                }
            )
    for flag in module_payload.get("quality_flags") or []:
        insights.append(
            {
                "severity": flag.get("severity") or "quality",
                "code": flag.get("rule_id") or "quality_flag",
                "title": "Data-quality flag",
                "detail": flag.get("explanation") or "A quality rule flagged this calculation run.",
            }
        )
    return insights[:20]


def _indicator_semantics(module_payload: dict, indicator_code: str) -> dict:
    row = next(
        (item for item in module_payload.get("indicators") or [] if item.get("indicator_code") == indicator_code),
        None,
    )
    catalog = _CATALOG.get(indicator_code) or {}
    spec = catalog.get("classification_spec") or {}
    mode = (row or {}).get("classification_mode") or spec.get("mode") or "unclassified"
    desired = (row or {}).get("desired_range") or (spec.get("green") if mode == "desired_range" else None)
    return {"classification_mode": mode, "desired_range": desired, "direction": catalog.get("direction")}


def _rank_rows(comparisons: list[dict], indicator_code: str, module_payload: dict) -> dict:
    semantics = _indicator_semantics(module_payload, indicator_code)
    ranking = rank_units(
        comparisons,
        indicator_code=indicator_code,
        classification_mode=semantics["classification_mode"],
        desired_range=semantics["desired_range"],
    )
    ranking["direction"] = semantics["direction"]
    return ranking


def _facility_comparisons(
    session: Session,
    *,
    user: User,
    org_unit: OrgUnit,
    period: str,
    module: str,
) -> list[dict]:
    programme = MODULE_PROGRAMME[module]
    codes = MODULE_INDICATORS[module]
    prepare_calculation_batch(session, org_unit=org_unit, periods=[period])
    rows = []
    try:
        for child in descendants(session, org_unit, include_self=False):
            if child.level_type != OrgUnitLevel.FACILITY.value:
                continue
            if not can_access_org_unit(session, user, child):
                continue
            run = run_calculation(
                session,
                org_unit=child,
                period=period,
                user=user,
                programme_codes=[programme],
                indicator_codes=codes,
            )
            values = _value_map(session, run)
            selection = _selection_map(run)
            rows.append(
                {
                    "org_unit_id": str(child.id),
                    "org_unit_code": child.code,
                    "org_unit_name": child.name,
                    "level_type": child.level_type,
                    "ownership": child.ownership,
                    "facility_level": child.facility_level,
                    "calculation_run_id": str(run.id),
                    "values": {
                        code: _indicator_payload(session, code, values.get(code), selection) for code in codes
                    },
                }
            )
    finally:
        clear_calculation_batch(session)
    return rows


def _population_payload(session: Session, org_unit: OrgUnit, period: str) -> dict:
    resolved = resolve_population(session, org_unit, period_key=period)
    return {
        "status": resolved.status,
        "population": resolved.population,
        "year": resolved.year,
        "source": resolved.source,
        "version_code": resolved.version_code,
        "version_id": str(resolved.version_id) if resolved.version_id else None,
        "approval_status": resolved.approval_status,
        "population_type": resolved.population_type,
        "reason": resolved.reason,
        "reason_code": resolved.reason_code,
        "selection_reason": resolved.selection_reason,
        "aggregation_level": resolved.aggregation_level,
        "facility_population_entry_id": (
            str(resolved.used_facility_entry_id) if resolved.used_facility_entry_id else None
        ),
        "official_or_estimated": resolved.population_type,
    }


def _export_surface(actions: set[str]) -> dict:
    can_export = ActionPermission.EXPORT.value in actions
    return {
        "phase6_implemented": True,
        "actions": [
            {
                "kind": "excel",
                "label": "Excel workbook (.xlsx)",
                "available": can_export,
                "implemented": True,
                "format": "xlsx",
                "message": "Generates a calculation-run workbook. Official MoH branding is still pending.",
            },
            {
                "kind": "powerpoint",
                "label": "PowerPoint briefing (.pptx)",
                "available": can_export,
                "implemented": True,
                "format": "pptx",
                "message": "Uses the platform-default template family until official slides are supplied.",
            },
            {
                "kind": "report",
                "label": "Narrative report (Markdown .md)",
                "available": can_export,
                "implemented": True,
                "format": "md",
                "message": (
                    "Writes a run-linked Markdown narrative. It is not a Word or PDF document; "
                    "official publishing templates are pending."
                ),
            },
            {
                "kind": "word",
                "label": "Word report (.docx)",
                "available": False,
                "implemented": False,
                "format": "docx",
                "message": "Unavailable until an approved Word generator and template exist.",
            },
            {
                "kind": "pdf",
                "label": "PDF report (.pdf)",
                "available": False,
                "implemented": False,
                "format": "pdf",
                "message": "Unavailable until an approved PDF generator and template exist.",
            },
        ],
    }


def _resolve_selected_indicator(module: str, module_payload: dict, selected_indicator: str | None) -> str:
    codes = MODULE_INDICATORS[module]
    if selected_indicator:
        if selected_indicator not in codes:
            raise AuthorizationError("invalid_input", "The selected indicator does not belong to this module.")
        return selected_indicator
    for code in codes[:6]:
        if code in UNSAFE_RANK_CODES:
            continue
        mode = _indicator_semantics(module_payload, code)["classification_mode"]
        if mode not in {"unclassified", "neutral_count"}:
            return code
    return codes[0]


def build_dashboard(
    session: Session,
    *,
    user: User,
    org_unit_id: UUID,
    period: str,
    module: str | None = None,
    comparison_period: str | None = None,
    selected_indicator: str | None = None,
    request_key: str | None = None,
) -> dict:
    require_action(session, user, ActionPermission.VIEW)
    org_unit = require_org_unit_access(session, user, org_unit_id)
    if user.is_system_admin:
        programmes = {item.value for item in ProgrammeCode}
    else:
        programmes = programme_scope_codes(session, user)
    modules = available_modules(programmes)
    chosen = module or default_module(programmes)
    if chosen not in MODULE_INDICATORS:
        raise AuthorizationError("invalid_input", "Analytical module is not recognised.")
    if chosen not in modules:
        raise AuthorizationError("forbidden", "The requested module is outside the authorised programme scope.")
    if selected_indicator and selected_indicator not in MODULE_INDICATORS[chosen]:
        raise AuthorizationError("invalid_input", "The selected indicator does not belong to this module.")
    screen = SCREEN_BY_LEVEL.get(org_unit.level_type, "national")
    include_children = screen in {"national", "regional", "sub_county"}
    payload = evaluate_module(
        session,
        user=user,
        org_unit_id=org_unit.id,
        period=period,
        module=chosen,
        comparison_period=comparison_period,
        include_children=include_children,
    )
    comparisons = payload.get("org_unit_comparison") or []
    if screen == "district":
        comparisons = _facility_comparisons(
            session,
            user=user,
            org_unit=org_unit,
            period=period,
            module=chosen,
        )
        payload["org_unit_comparison"] = comparisons
        payload["comparison_grain"] = "facility"
    elif screen == "facility":
        payload["comparison_grain"] = "none"
    else:
        payload["comparison_grain"] = "direct_children"

    kpi_codes = MODULE_INDICATORS[chosen][:6]
    kpis = [row for row in payload["indicators"] if row.get("indicator_code") in kpi_codes]
    rank_code = _resolve_selected_indicator(chosen, payload, selected_indicator)
    population = _population_payload(session, org_unit, period)
    effective_date = parse_period(period).end
    geometry = map_feature_collection(session, user, org_unit, as_of=effective_date)
    geometry_meta = {key: value for key, value in geometry.items() if key != "features"}
    if screen == "facility":
        map_rows = [
            {
                "org_unit_id": str(org_unit.id),
                "calculation_run_id": payload.get("current_run_id"),
                "values": {
                    row.get("indicator_code"): row for row in payload["indicators"] if row.get("indicator_code")
                },
            }
        ]
    else:
        map_rows = comparisons
    map_block = build_map_block(
        session,
        user,
        parent=org_unit,
        value_rows=map_rows,
        indicator_code=rank_code,
        effective_date=effective_date,
    )
    actions = user_actions(session, user)
    catalog_rows = []
    for row in payload["indicators"]:
        spec = _CATALOG.get(row.get("indicator_code") or "", {})
        catalog_rows.append(
            {
                **row,
                "denominator_type": spec.get("denominator_type"),
                "direction": row.get("direction") or spec.get("direction"),
                "population_derived": spec.get("denominator_type")
                == DenominatorType.POPULATION_DERIVED.value,
            }
        )
    payload["indicators"] = catalog_rows
    dashboard = {
        "screen": screen,
        "scope": {
            **_summary(org_unit),
            "district": _summary(_ancestor_of_type(session, org_unit, OrgUnitLevel.DISTRICT.value)),
            "sub_county": _summary(_ancestor_of_type(session, org_unit, OrgUnitLevel.SUB_COUNTY.value)),
        },
        "ancestors": [
            _summary(item)
            for item in ancestors(session, org_unit)
            if can_access_org_unit(session, user, item)
        ],
        "period": period,
        "comparison_period": payload["comparison_period"],
        "module": chosen,
        "available_modules": modules,
        "programmes": sorted(programmes),
        "actions": sorted(actions),
        "can_edit_population": ActionPermission.EDIT_POPULATION.value in actions,
        "population": population,
        "kpis": kpis,
        "module_result": payload,
        "facility_scorecard": comparisons if screen == "district" else [],
        "ranking": _rank_rows(comparisons, rank_code, payload),
        "selected_indicator": rank_code,
        "insights": _insights(payload, population),
        "geometry": geometry_meta,
        "map": map_block,
        "exports": _export_surface(actions),
        "generated_at": datetime.now(UTC).isoformat(),
        "fixture_label": None,
    }
    persist_snapshot(
        session,
        user=user,
        dashboard=dashboard,
        evidence=evidence_package(dashboard),
        request_key=request_key,
        request={
            "org_unit_id": str(org_unit.id),
            "period": period,
            "module": module,
            "comparison_period": comparison_period,
            "selected_indicator": selected_indicator,
        },
    )
    return dashboard

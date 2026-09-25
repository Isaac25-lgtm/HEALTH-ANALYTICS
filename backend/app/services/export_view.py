"""A presentation model for exports, built only from a committed analysis snapshot.

Every number here is copied from the snapshot. Nothing is recalculated, re-aggregated or
re-classified: formatting (units, labels, rounding for display) is the only transformation, and it
mirrors the dashboard (``frontend/src/lib/status.ts``) so a download reads like the screen.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.domain.periods import PeriodError, parse_period

STATUS_LABELS = {
    "green": "On track",
    "yellow": "Needs attention",
    "red": "Off track",
    "blue": "Non-assessable",
    "n_a": "No approved threshold",
    "unclassified": "Unclassified",
    "missing": "No data",
}

# Heat fills and ink, shared by every format. Same palette as the dashboard's heat tokens.
STATUS_FILL = {
    "green": "B7E4C4",
    "yellow": "FDE39A",
    "red": "F6B7B7",
    "blue": "CADFFA",
    "n_a": "EEF3F7",
    "unclassified": "EEF3F7",
    "missing": "F4F6F8",
}
STATUS_INK = {
    "green": "0D5A35",
    "yellow": "6A4600",
    "red": "8C1B22",
    "blue": "123F80",
    "n_a": "334155",
    "unclassified": "334155",
    "missing": "64748B",
}
# Solid accents for bars, card edges and map fills.
STATUS_SOLID = {
    "green": "17784C",
    "yellow": "D39A00",
    "red": "C0262F",
    "blue": "2F6DB5",
    "n_a": "94A3B8",
    "unclassified": "94A3B8",
    "missing": "CBD5E1",
}
NAVY = "06345A"
NAVY_LIGHT = "E8F1FA"
INK = "1E293B"
MUTED = "64748B"

MODULE_TITLES = {
    "anc": "ANC",
    "intrapartum": "Intrapartum and newborn",
    "immunization": "Immunization",
    "mpdsr": "MPDSR",
}
LEVEL_UNIT_LABELS = {
    "country": "Regions",
    "region": "Districts and cities",
    "sub_region": "Districts and cities",
    "district": "Facilities",
    "city": "Facilities",
    "sub_county": "Facilities",
}
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def resolve_status(value: dict | None) -> str:
    """Same precedence as the dashboard: BLUE first, then missing, then the performance status."""
    if not value:
        return "missing"
    if value.get("quality_status") == "blue" or value.get("status") == "blue":
        return "blue"
    if value.get("raw_value") is None:
        return "missing"
    return value.get("status") or value.get("performance_status") or "n_a"


def status_label(status: str | None) -> str:
    return STATUS_LABELS.get(status or "n_a", STATUS_LABELS["n_a"])


def format_measure(value: dict | None) -> str:
    """The value as the dashboard shows it: "92.4%", "1,204", or "No data"."""
    if not value or value.get("raw_value") is None:
        return "No data"
    unit = value.get("unit")
    display = value.get("display_value")
    raw = value.get("raw_value")
    if display:
        if unit == "%":
            return display if display.endswith("%") else f"{display}%"
        if unit == "count":
            try:
                return f"{float(display.replace(',', '')):,.0f}"
            except ValueError:
                return display
        return f"{display} {unit}" if unit and unit not in display else display
    if unit == "count":
        return f"{raw:,.0f}"
    text = f"{raw:.1f}"
    return f"{text}%" if unit == "%" else (f"{text} {unit}" if unit else text)


def excel_number_format(unit: str | None, precision: int | None) -> str:
    """A cell format that displays the exact stored value the way the dashboard rounds it."""
    places = 1 if precision is None else max(int(precision), 0)
    decimals = "0" if places == 0 else "0." + "0" * places
    if unit == "%":
        return f'{decimals}"%"'
    if unit == "count":
        return "#,##0"
    return f"#,##{decimals}"


def change_text(indicator: dict) -> str:
    change = indicator.get("change") or {}
    if change.get("percentage_point_change") is not None:
        value = change["percentage_point_change"]
        return f"{value:+.1f} pp"
    if change.get("absolute_change") is not None:
        value = change["absolute_change"]
        return f"{value:+,.1f}"
    return "No comparison"


def interpretation_text(indicator: dict) -> str:
    interpretation = (indicator.get("change") or {}).get("interpretation")
    return {"improved": "Improved", "deteriorated": "Deteriorated", "unchanged": "Unchanged"}.get(
        interpretation or "", ""
    )


def thresholds_text(indicator: dict) -> str:
    thresholds = indicator.get("thresholds")
    if isinstance(thresholds, dict):
        return thresholds.get("text") or ""
    return str(thresholds or "")


def period_label(key: str | None) -> str:
    """Readable period: "Jun 2025", "Nov 2024 – Dec 2025", "FY2025/26 Q1 (Jul–Sep 2025)"."""
    if not key:
        return ""
    try:
        spec = parse_period(key)
    except PeriodError:
        return key
    if spec.kind == "month":
        return f"{MONTHS[spec.start.month - 1]} {spec.start.year}"
    if spec.kind == "range":
        return f"{MONTHS[spec.start.month - 1]} {spec.start.year} – {MONTHS[spec.end.month - 1]} {spec.end.year}"
    if spec.kind == "fy_quarter":
        return (
            f"{spec.parent_fy} Q{spec.key[-1]} ({MONTHS[spec.start.month - 1]}–"
            f"{MONTHS[spec.end.month - 1]} {spec.end.year})"
        )
    return spec.key


def short_period_label(key: str) -> str:
    try:
        spec = parse_period(key)
    except PeriodError:
        return key
    if spec.kind == "month":
        return f"{MONTHS[spec.start.month - 1]} {str(spec.start.year)[2:]}"
    return period_label(key)


@dataclass
class ExportView:
    scope_name: str
    level_type: str
    module: str
    module_title: str
    period: str
    period_label: str
    comparison: str | None
    comparison_label: str
    generated_at: str
    run_id: str | None
    snapshot_id: str | None
    indicators: list[dict]
    kpis: list[dict]
    unit_label: str
    units: list[dict]
    unit_columns: list[dict]
    ranking: dict
    ranking_indicator_name: str
    trends: list[dict]
    trend_indicator: dict | None
    population: dict
    quality_flags: list[dict]
    map_features: list[dict] = field(default_factory=list)
    map_indicator_name: str = ""
    map_note: str = ""

    @property
    def title(self) -> str:
        return f"{self.scope_name} {self.module_title} briefing"

    @property
    def subtitle(self) -> str:
        comparison = f" compared with {self.comparison_label}" if self.comparison_label else ""
        return f"{self.period_label}{comparison}"


def _indicator_name(indicators: list[dict], code: str | None) -> str:
    for row in indicators:
        if row.get("indicator_code") == code:
            return row.get("name") or code or ""
    return code or ""


def build_export_view(dashboard: dict, package: dict, map_features: dict | None = None) -> ExportView:
    module_result = dashboard.get("module_result") or {}
    indicators = list(module_result.get("indicators") or [])
    scope = dashboard.get("scope") or {}
    level_type = scope.get("level_type") or (package.get("scope") or {}).get("level_type") or ""
    module = str(dashboard.get("module") or package.get("module") or "")
    kpi_codes = [row.get("indicator_code") for row in dashboard.get("kpis") or []]
    kpis = [row for row in indicators if row.get("indicator_code") in kpi_codes][:6] or indicators[:6]

    # The unit grid matches the screen: districts on national/regional views, facilities on
    # district views, otherwise the direct children.
    units = list(
        module_result.get("district_comparison")
        or dashboard.get("facility_scorecard")
        or module_result.get("org_unit_comparison")
        or []
    )
    if module_result.get("district_comparison"):
        unit_label = "Districts and cities"
    else:
        unit_label = LEVEL_UNIT_LABELS.get(level_type, "Units")
    units.sort(key=lambda row: str(row.get("org_unit_name") or ""))

    ranking = dashboard.get("ranking") or {}
    selected = dashboard.get("selected_indicator") or ranking.get("indicator_code")
    trend_indicator = next((row for row in indicators if row.get("indicator_code") == selected), None)
    map_block = dashboard.get("map") or {}
    features = list((map_features or {}).get("features") or [])
    comparison = dashboard.get("comparison_period") or package.get("comparison_period")
    return ExportView(
        scope_name=scope.get("name") or (package.get("scope") or {}).get("org_unit_name") or "",
        level_type=level_type,
        module=module,
        module_title=MODULE_TITLES.get(module, module),
        period=str(dashboard.get("period") or package.get("period") or ""),
        period_label=period_label(dashboard.get("period") or package.get("period")),
        comparison=comparison,
        comparison_label=period_label(comparison),
        generated_at=datetime.now(UTC).strftime("%d %b %Y %H:%M UTC"),
        run_id=package.get("current_run_id") or module_result.get("current_run_id"),
        snapshot_id=dashboard.get("analysis_snapshot_id") or package.get("analysis_snapshot_id"),
        indicators=indicators,
        kpis=kpis,
        unit_label=unit_label,
        units=units,
        unit_columns=kpis,
        ranking=ranking,
        ranking_indicator_name=_indicator_name(indicators, ranking.get("indicator_code")),
        trends=list(module_result.get("trends") or []),
        trend_indicator=trend_indicator,
        population=dashboard.get("population") or package.get("population") or {},
        quality_flags=list(package.get("quality_flags") or []),
        map_features=features,
        map_indicator_name=_indicator_name(indicators, map_block.get("selected_indicator")),
        map_note=(
            f"Boundaries in force on {map_block.get('geometry_effective_date')}"
            if map_block.get("geometry_effective_date")
            else ""
        ),
    )


def trend_series(view: ExportView) -> list[tuple[str, float | None]]:
    """(label, value) for the selected indicator across the snapshot's trend periods."""
    code = (view.trend_indicator or {}).get("indicator_code")
    series = []
    for row in view.trends:
        value = ((row.get("values") or {}).get(code) or {}).get("raw_value") if code else None
        series.append((short_period_label(str(row.get("period"))), value))
    return series

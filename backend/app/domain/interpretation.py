"""Direction-aware interpretation of change and ranking.

This module never calculates an indicator. It reads calculated values and the approved
classification mode of each indicator version and decides only whether a movement may
be described as improvement or deterioration, and whether units may be ranked.
"""

from __future__ import annotations

from app.domain.enums import ChangeInterpretation, PerformanceStatus
from app.domain.modules import MODULE_INDICATORS

HIGHER_MODES = frozenset({"higher_is_better", "bounded_higher", "maternal_coverage"})
LOWER_MODES = frozenset({"lower_is_better", "teenage_pregnancy", "mmr"})
RANGE_MODES = frozenset({"desired_range"})
INTERPRETABLE_MODES = HIGHER_MODES | LOWER_MODES | RANGE_MODES

# Small-number mortality ratios and event-derived MPDSR measures are not ranked without an
# approved safe-ranking rule; their instability makes league tables misleading.
UNSAFE_RANK_CODES = frozenset({"PMR", "FRESH_STILLBIRTH_RATE", "MMR", *MODULE_INDICATORS["mpdsr"]})

ORDER_RULES = {
    "higher": "higher_values_rank_first",
    "lower": "lower_values_rank_first",
    "range": "closest_to_desired_range_ranks_first",
}


def _is_blue(value: dict) -> bool:
    blue = PerformanceStatus.BLUE.value
    return value.get("status") == blue or value.get("quality_status") == blue


def _state(value: dict | None) -> str:
    if not value or value.get("raw_value") is None:
        return "missing"
    if _is_blue(value):
        return "non_assessable"
    return "assessable"


def range_distance(value: float, desired_range: list[float] | tuple[float, float]) -> float:
    low, high = float(desired_range[0]), float(desired_range[1])
    if value < low:
        return low - value
    if value > high:
        return value - high
    return 0.0


def _rounded(value: float, precision: int | None) -> float:
    return round(float(value), int(precision) if precision is not None else 1)


def interpret_change(
    *,
    classification_mode: str | None,
    current: dict | None,
    previous: dict | None,
    desired_range: list[float] | None = None,
    precision: int | None = 1,
) -> dict:
    mode = classification_mode or "unclassified"
    transition = [
        (previous or {}).get("status") if previous else None,
        (current or {}).get("status") if current else None,
    ]
    result = {
        "interpretation": ChangeInterpretation.NOT_INTERPRETED.value,
        "classification_mode": mode,
        "status_transition": transition,
        "reason": None,
    }
    states = {_state(current), _state(previous)}
    if "missing" in states:
        result["reason"] = "A current or comparison value is missing, so the change is not interpreted."
        return result
    if "non_assessable" in states:
        result["reason"] = "BLUE non-assessable values are never described as improvement or deterioration."
        return result
    if mode not in INTERPRETABLE_MODES:
        result["reason"] = (
            "No approved classification rule exists for this indicator, so only the numeric change is reported."
        )
        return result
    now = _rounded(current["raw_value"], precision)
    before = _rounded(previous["raw_value"], precision)
    if mode in RANGE_MODES:
        if not desired_range:
            result["reason"] = "The desired range is not configured, so the change is not interpreted."
            return result
        gap_now = range_distance(now, desired_range)
        gap_before = range_distance(before, desired_range)
        if gap_now < gap_before:
            result["interpretation"] = ChangeInterpretation.IMPROVED.value
            result["reason"] = "The value moved toward the approved desired range."
        elif gap_now > gap_before:
            result["interpretation"] = ChangeInterpretation.DETERIORATED.value
            result["reason"] = "The value moved away from the approved desired range."
        else:
            result["interpretation"] = ChangeInterpretation.UNCHANGED.value
            result["reason"] = "Distance from the approved desired range did not change."
        return result
    delta = now - before
    if delta == 0:
        result["interpretation"] = ChangeInterpretation.UNCHANGED.value
        result["reason"] = "No change at the displayed precision."
        return result
    better = delta > 0 if mode in HIGHER_MODES else delta < 0
    result["interpretation"] = (
        ChangeInterpretation.IMPROVED.value if better else ChangeInterpretation.DETERIORATED.value
    )
    result["reason"] = (
        "Higher values are better for this indicator."
        if mode in HIGHER_MODES
        else "Lower values are better for this indicator."
    )
    return result


def _order_kind(mode: str) -> str | None:
    if mode in HIGHER_MODES:
        return "higher"
    if mode in LOWER_MODES:
        return "lower"
    if mode in RANGE_MODES:
        return "range"
    return None


def rank_units(
    rows: list[dict],
    *,
    indicator_code: str,
    classification_mode: str | None,
    desired_range: list[float] | None = None,
    limit: int = 5,
) -> dict:
    """Rank child units with direction/range logic. Never sorts raw values blindly."""
    mode = classification_mode or "unclassified"
    result: dict = {
        "indicator_code": indicator_code,
        "classification_mode": mode,
        "ranking_allowed": False,
        "order_rule": None,
        "reason": None,
        "reason_code": None,
        "best": [],
        "worst": [],
        "top": [],
        "bottom": [],
        "ordered_org_unit_ids": [],
        "excluded": {"blue": [], "missing": [], "non_assessable": []},
    }
    if indicator_code in UNSAFE_RANK_CODES:
        result["reason_code"] = "unsafe_small_count_indicator"
        result["reason"] = (
            "Small-number mortality and MPDSR measures are not ranked without an approved safe-ranking rule."
        )
        return result
    kind = _order_kind(mode)
    if kind is None or (kind == "range" and not desired_range):
        result["reason_code"] = "no_approved_ranking_rule"
        result["reason"] = "No approved ranking rule exists for this indicator (thresholds TBD or neutral count)."
        return result
    eligible: list[tuple[float, str, dict]] = []
    for row in rows:
        value = (row.get("values") or {}).get(indicator_code) or {}
        entry = {
            "org_unit_id": row.get("org_unit_id"),
            "org_unit_code": row.get("org_unit_code"),
            "org_unit_name": row.get("org_unit_name"),
            "level_type": row.get("level_type"),
            "ownership": row.get("ownership"),
            "facility_level": row.get("facility_level"),
            "raw_value": value.get("raw_value"),
            "display_value": value.get("display_value"),
            "unit": value.get("unit"),
            "status": value.get("status"),
        }
        if value.get("raw_value") is None:
            result["excluded"]["missing"].append(entry)
            continue
        if _is_blue(value):
            result["excluded"]["blue"].append(entry)
            continue
        if value.get("status") in {None, PerformanceStatus.NA.value}:
            result["excluded"]["non_assessable"].append(entry)
            continue
        raw = float(value["raw_value"])
        if kind == "higher":
            score = -raw
        elif kind == "lower":
            score = raw
        else:
            score = range_distance(raw, desired_range)
        eligible.append((score, str(entry.get("org_unit_name") or ""), entry))
    eligible.sort(key=lambda item: (item[0], item[1]))
    ordered = [entry for _, _, entry in eligible]
    result["ranking_allowed"] = True
    result["order_rule"] = ORDER_RULES[kind]
    result["best"] = ordered[:limit]
    result["worst"] = list(reversed(ordered[-limit:])) if ordered else []
    result["top"] = result["best"]
    result["bottom"] = result["worst"]
    result["ordered_org_unit_ids"] = [entry["org_unit_id"] for entry in ordered]
    return result

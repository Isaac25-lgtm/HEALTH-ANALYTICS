from __future__ import annotations

from app.domain.enums import PerformanceStatus


def quantize(value: float, precision: int) -> float:
    return float(f"{value:.{precision}f}")


def classify(value: float, spec: dict | None) -> str:
    if not spec:
        return PerformanceStatus.NA.value
    mode = spec.get("mode")
    precision = int(spec.get("precision") or 1)
    q = quantize(value, precision)
    if mode in {None, "unclassified", "neutral_count"}:
        return PerformanceStatus.NA.value
    if mode == "higher_is_better":
        if q >= spec["green_min"]:
            return PerformanceStatus.GREEN.value
        if q >= spec["yellow_min"]:
            return PerformanceStatus.YELLOW.value
        return PerformanceStatus.RED.value
    if mode == "bounded_higher":
        if q > spec.get("cap", 100):
            return PerformanceStatus.BLUE.value
        if q >= spec["green_min"]:
            return PerformanceStatus.GREEN.value
        if q >= spec["yellow_min"]:
            return PerformanceStatus.YELLOW.value
        return PerformanceStatus.RED.value
    if mode == "lower_is_better":
        if q <= spec["green_max"]:
            return PerformanceStatus.GREEN.value
        if q <= spec["yellow_max"]:
            return PerformanceStatus.YELLOW.value
        return PerformanceStatus.RED.value
    if mode == "teenage_pregnancy":
        if q < 5:
            return PerformanceStatus.GREEN.value
        if q <= 12.9:
            return PerformanceStatus.YELLOW.value
        return PerformanceStatus.RED.value
    if mode == "mmr":
        if q <= 183:
            return PerformanceStatus.GREEN.value
        if q <= 300:
            return PerformanceStatus.YELLOW.value
        return PerformanceStatus.RED.value
    if mode == "maternal_coverage":
        if q == 100:
            return PerformanceStatus.GREEN.value
        if 90 <= q < 100:
            return PerformanceStatus.YELLOW.value
        if q > 100:
            return PerformanceStatus.BLUE.value
        return PerformanceStatus.RED.value
    if mode == "desired_range":
        green = spec["green"]
        if green[0] <= q <= green[1]:
            return PerformanceStatus.GREEN.value
        for low, high in spec.get("yellow", []):
            if low <= q <= high:
                return PerformanceStatus.YELLOW.value
        return PerformanceStatus.RED.value
    return PerformanceStatus.NA.value


def display_value(raw: float | None, precision: int, unit: str) -> str | None:
    if raw is None:
        return None
    formatted = f"{raw:.{precision}f}"
    if unit == "count":
        return str(int(round(raw)))
    return formatted

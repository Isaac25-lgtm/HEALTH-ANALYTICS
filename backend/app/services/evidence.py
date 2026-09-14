from __future__ import annotations

import hashlib
import json
import re
from typing import Any

SENSITIVE_KEYS = {
    "event_uid",
    "eventuid",
    "event_snapshot_ids",
    "trackedentity",
    "tracked_entity",
    "patient",
    "patient_name",
    "mother",
    "mother_name",
    "full_name",
    "username",
    "clinician",
    "clinician_name",
    "narrative",
    "notes",
    "identifier",
    "phone",
    "address",
}

# Blame, negligence and unsupported causal attribution. Word forms are matched as whole
# tokens with their inflections, so "negligence", "negligent", "blamed" and "preventable
# deaths" are all caught. The AI may describe an observed association or a documented
# category, but may not assign blame or causation without adjudicated evidence.
BLAME_CAUSATION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("negligence", re.compile(r"\bnegligen(?:ce|t|tly)\b", re.IGNORECASE)),
    ("blame", re.compile(r"\bblam(?:e|ed|es|ing|eworthy|able)\b", re.IGNORECASE)),
    (
        "preventable_death",
        re.compile(r"\bpreventable\s+(?:maternal\s+|perinatal\s+|neonatal\s+)?deaths?\b", re.IGNORECASE),
    ),
    (
        "caused_by_staff",
        re.compile(
            r"\bcaused\s+by\s+(?:the\s+)?(?:staff|health\s+workers?|healthcare\s+workers?|nurses?|midwives|midwife|"
            r"doctors?|clinicians?|providers?|facility|facilities|hospital)\b",
            re.IGNORECASE,
        ),
    ),
    ("staff_failure", re.compile(r"\bstaff\s+failures?\b|\bfailures?\s+(?:of|by)\s+(?:the\s+)?staff\b", re.IGNORECASE)),
    (
        "facility_failure",
        re.compile(r"\bfacility\s+failures?\b|\bfailures?\s+(?:of|by)\s+(?:the\s+)?facilit(?:y|ies)\b", re.IGNORECASE),
    ),
    (
        "poor_care_caused",
        re.compile(r"\bpoor\s+(?:quality\s+)?care\s+(?:caused|causes|causing|led\s+to|leads\s+to)\b", re.IGNORECASE),
    ),
    (
        "responsible_for_death",
        re.compile(r"\bresponsible\s+for\s+(?:the\s+|these\s+|this\s+|her\s+|their\s+)?deaths?\b", re.IGNORECASE),
    ),
    ("who_caused", re.compile(r"\bwho\s+(?:caused|is\s+to\s+blame|was\s+at\s+fault)\b", re.IGNORECASE)),
    ("fault", re.compile(r"\bat\s+fault\b|\bwhose\s+fault\b", re.IGNORECASE)),
    ("malpractice", re.compile(r"\bmalpractice\b", re.IGNORECASE)),
    ("dismissal", re.compile(r"\bshould\s+be\s+(?:fired|sacked|dismissed|punished|disciplined)\b", re.IGNORECASE)),
)

STATEMENT_KINDS = {"observation", "association", "data_quality", "insufficient_evidence", "recommendation"}


def blame_or_causation_matches(text: str | None) -> list[str]:
    return [name for name, pattern in BLAME_CAUSATION_PATTERNS if pattern.search(text or "")]


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            if str(key).lower().replace("-", "_") in SENSITIVE_KEYS:
                continue
            cleaned[key] = redact(item)
        return cleaned
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str) and re.search(r"\b[A-Za-z][A-Za-z0-9]{10}\b", value) and "event" in value.lower():
        return "[redacted]"
    return value


def _compact(value: dict) -> dict:
    """Drop unrecorded (None) fields. Absence means "not recorded"; nothing is invented."""
    return {key: item for key, item in value.items() if item is not None}


def _grouped_quality_flags(flags: list[dict]) -> list[dict]:
    grouped: dict[tuple, dict] = {}
    for flag in flags:
        key = (flag.get("rule_id"), flag.get("severity"), flag.get("explanation"))
        entry = grouped.setdefault(
            key,
            {"rule_id": key[0], "severity": key[1], "explanation": key[2], "occurrences": 0},
        )
        entry["occurrences"] += 1
    return list(grouped.values())


def _indicator_evidence(row: dict) -> dict:
    thresholds = row.get("thresholds") or {}
    change = _compact(row.get("change") or {})
    return _compact({
        "indicator_code": row.get("indicator_code"),
        "name": row.get("name"),
        "raw_value": row.get("raw_value"),
        "display_value": row.get("display_value"),
        "unit": row.get("unit"),
        "status": row.get("status"),
        "quality_status": row.get("quality_status"),
        "numerator": row.get("numerator"),
        "denominator": row.get("denominator"),
        "blue_reason": row.get("blue_reason"),
        "reason_code": row.get("reason_code"),
        "change": change,
        "interpretation": change.get("interpretation"),
        "direction": row.get("direction"),
        "classification_mode": row.get("classification_mode"),
        "desired_range": row.get("desired_range"),
        "thresholds": thresholds.get("text") if isinstance(thresholds, dict) else thresholds,
        "threshold_state": thresholds.get("state") if isinstance(thresholds, dict) else None,
        "formula_version": row.get("formula_version"),
        "formula_version_rule": row.get("formula_version_rule"),
        "formula_version_effective_date": row.get("formula_version_effective_date"),
        "mapping_version": row.get("mapping_version"),
        "aggregation_policy": row.get("aggregation_policy"),
        "aggregation_level": row.get("aggregation_level"),
        "population_year": row.get("population_year"),
        "population_version_id": row.get("population_version_id"),
        "facility_population_entry_id": row.get("facility_population_entry_id"),
        "source_freshness_at": row.get("source_freshness_at"),
        "event_coverage_status": row.get("event_coverage_status"),
        "calculation_run_id": row.get("calculation_run_id"),
    })


def evidence_package(dashboard: dict) -> dict:
    module = dashboard.get("module_result") or {}
    package = {
        "scope": {
            "org_unit_code": dashboard.get("scope", {}).get("code"),
            "org_unit_name": dashboard.get("scope", {}).get("name"),
            "level_type": dashboard.get("scope", {}).get("level_type"),
        },
        "period": dashboard.get("period"),
        "comparison_period": dashboard.get("comparison_period"),
        "module": dashboard.get("module"),
        "current_run_id": module.get("current_run_id"),
        "comparison_run_id": module.get("comparison_run_id"),
        "population": dashboard.get("population"),
        "freshness": module.get("freshness"),
        "indicators": [_indicator_evidence(row) for row in module.get("indicators") or []],
        "quality_flags": _grouped_quality_flags(module.get("quality_flags") or []),
        "mpdsr": redact(module.get("mpdsr") or {}),
        "prompt_instruction": (
            "Explain only these verified facts. Do not invent values, causes, blame, "
            "or missing denominators. Describe observed associations as associations, never as causes. "
            "If evidence is insufficient, say so."
        ),
    }
    return redact(package)


def evidence_hash(package: dict) -> str:
    encoded = json.dumps(package, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def contains_unsupported_number(text: str, package: dict) -> bool:
    allowed = set(re.findall(r"-?\d+(?:\.\d+)?", json.dumps(package, default=str)))
    mentioned = set(re.findall(r"-?\d+(?:\.\d+)?", text or ""))
    extras = {item for item in mentioned if item not in allowed and item not in {"0", "1", "2", "3"}}
    return bool(extras)


def question_is_unsupported(question: str) -> bool:
    return bool(blame_or_causation_matches(question))


def validate_statements(statements: Any, package: dict) -> tuple[list[dict] | None, str | None]:
    """Schema-validate provider statements against the evidence package.

    Each statement must name its kind, cite indicator codes present in the package, avoid
    unsupported numbers, and avoid blame or causal attribution.
    """
    if not isinstance(statements, list) or not statements:
        return None, "schema_invalid"
    codes = {row.get("indicator_code") for row in package.get("indicators") or [] if row.get("indicator_code")}
    cleaned: list[dict] = []
    for item in statements:
        if not isinstance(item, dict):
            return None, "schema_invalid"
        text = item.get("text")
        kind = item.get("kind")
        refs = item.get("evidence_refs") or []
        if not isinstance(text, str) or not text.strip() or kind not in STATEMENT_KINDS:
            return None, "schema_invalid"
        if not isinstance(refs, list) or any(ref not in codes for ref in refs):
            return None, "evidence_reference_invalid"
        if kind != "insufficient_evidence" and not refs:
            return None, "evidence_reference_missing"
        if blame_or_causation_matches(text):
            return None, "unsafe_causal_or_blame_language"
        if contains_unsupported_number(text, package):
            return None, "unsupported_numeric_claim"
        cleaned.append({"text": text.strip(), "kind": kind, "evidence_refs": refs})
    return cleaned, None

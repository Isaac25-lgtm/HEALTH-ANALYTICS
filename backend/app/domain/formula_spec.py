from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class FormulaValidationError(ValueError):
    pass


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NumeratorSpec(_Strict):
    mode: Literal["event_count"]
    event_type: str
    completed_only: bool = True
    timely: Literal["notification", "review"] | None = None


class DenominatorSpec(_Strict):
    mode: Literal["population", "source_keys"]
    coefficient: float | None = None
    period_adjust: bool = False
    source_keys: list[str] = Field(default_factory=list)


class FormulaSpec(_Strict):
    kind: Literal["ratio", "count", "direct_percentage", "dropout"]
    source_keys: list[str] = Field(default_factory=list)
    source_key: str | None = None
    first_key: str | None = None
    final_key: str | None = None
    numerator_keys: list[str] = Field(default_factory=list)
    numerator: NumeratorSpec | None = None
    denominator: DenominatorSpec | None = None
    over_100: str | None = None
    bounded_proportion: bool | None = None
    reconciliation_blue: bool | None = None
    require_all_components: bool = True


class ClassificationSpec(_Strict):
    mode: str
    green_min: float | None = None
    yellow_min: float | None = None
    green_max: float | None = None
    yellow_max: float | None = None
    cap: float | None = None
    green: list[float] | None = None
    yellow: list[list[float]] | None = None
    precision: int = 1


ALLOWED_CLASSIFICATION_MODES = {
    "unclassified",
    "neutral_count",
    "higher_is_better",
    "bounded_higher",
    "lower_is_better",
    "teenage_pregnancy",
    "mmr",
    "maternal_coverage",
    "desired_range",
}


def validate_formula_spec(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not payload:
        raise FormulaValidationError("Formula specification is required.")
    try:
        spec = FormulaSpec.model_validate(payload)
    except ValidationError as exc:
        raise FormulaValidationError(str(exc)) from exc
    if spec.kind == "direct_percentage" and not spec.source_key:
        raise FormulaValidationError("direct_percentage requires source_key.")
    if spec.kind == "dropout" and (not spec.first_key or not spec.final_key):
        raise FormulaValidationError("dropout requires first_key and final_key.")
    if spec.kind == "count" and not spec.source_keys and spec.numerator is None:
        raise FormulaValidationError("count requires source_keys or an event_count numerator.")
    return spec.model_dump()


def validate_classification_spec(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not payload:
        raise FormulaValidationError("Classification specification is required.")
    try:
        spec = ClassificationSpec.model_validate(payload)
    except ValidationError as exc:
        raise FormulaValidationError(str(exc)) from exc
    if spec.mode not in ALLOWED_CLASSIFICATION_MODES:
        raise FormulaValidationError(f"Unknown classification mode: {spec.mode}")
    return spec.model_dump()

"""Formula-source coverage: does a mapping set actually support a programme's indicators?

Existence of *some* mapping is not coverage. A programme whose formulas need forty-eight source
keys is not calculable because one key is mapped, and a refresh that proceeds anyway produces a
green freshness state over indicators that can never resolve. Coverage is therefore evaluated
against the formulas themselves, per programme, mapping version and period.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.indicator_catalog import INDICATOR_CATALOG
from app.models import Programme, SourceMapping


class CoverageError(RuntimeError):
    """A programme cannot be extracted or calculated with the mappings that exist."""

    def __init__(self, code: str, message: str, report: CoverageReport) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.report = report


def _source_keys_of(spec, acc: set[str]) -> None:
    if isinstance(spec, dict):
        for key, value in spec.items():
            if key in {"numerator_keys", "keys", "source_keys"} and isinstance(value, list):
                acc.update(str(item) for item in value)
            elif key in {"key", "source_key"} and isinstance(value, str):
                acc.add(value)
            else:
                _source_keys_of(value, acc)
    elif isinstance(spec, list):
        for value in spec:
            _source_keys_of(value, acc)


def required_source_keys(programme_code: str) -> set[str]:
    """Every internal source key the programme's approved formulas depend on."""
    required: set[str] = set()
    for indicator in INDICATOR_CATALOG:
        if indicator.get("programme") != programme_code:
            continue
        _source_keys_of(indicator.get("formula_spec"), required)
    return required


@dataclass
class CoverageReport:
    programme_code: str
    mapping_version: str
    required: list[str] = field(default_factory=list)
    resolved: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return bool(self.required) and not self.unresolved

    def as_dict(self) -> dict:
        return {
            "programme": self.programme_code,
            "mapping_version": self.mapping_version,
            "required_count": len(self.required),
            "resolved_count": len(self.resolved),
            "unresolved_count": len(self.unresolved),
            "unresolved_source_keys": sorted(self.unresolved),
            "complete": self.complete,
        }


def evaluate_coverage(
    session: Session,
    *,
    programme_id: UUID,
    mapping_version: str,
    as_of: date | None = None,
) -> CoverageReport:
    """Compare the formulas' required source keys against the enabled mappings in force."""
    programme = session.get(Programme, programme_id)
    programme_code = programme.code if programme else ""
    required = required_source_keys(programme_code)

    rows = session.scalars(
        select(SourceMapping).where(
            SourceMapping.programme_id == programme_id,
            SourceMapping.mapping_version == mapping_version,
            SourceMapping.enabled.is_(True),
        )
    ).all()
    resolved = {
        row.internal_source_key
        for row in rows
        if row.dhis2_item_uid
        and (as_of is None or not row.valid_from or row.valid_from <= as_of)
        and (as_of is None or not row.valid_to or row.valid_to >= as_of)
    }
    covered = required & resolved
    return CoverageReport(
        programme_code=programme_code,
        mapping_version=mapping_version,
        required=sorted(required),
        resolved=sorted(covered),
        unresolved=sorted(required - resolved),
    )


def ensure_coverage(
    session: Session,
    *,
    programme_id: UUID,
    mapping_version: str,
    as_of: date | None = None,
) -> CoverageReport:
    """Raise unless every source key the programme's formulas need is mapped and in force."""
    report = evaluate_coverage(
        session, programme_id=programme_id, mapping_version=mapping_version, as_of=as_of
    )
    if not report.required:
        raise CoverageError(
            "programme_has_no_formulas",
            f"No approved formulas define source keys for programme {report.programme_code!r}.",
            report,
        )
    if report.unresolved:
        raise CoverageError(
            "mapping_coverage_incomplete",
            (
                f"{len(report.unresolved)} of {len(report.required)} source keys required by "
                f"{report.programme_code} formulas are unmapped in version {mapping_version!r}: "
                f"{', '.join(report.unresolved[:8])}"
                + ("…" if len(report.unresolved) > 8 else "")
            ),
            report,
        )
    return report

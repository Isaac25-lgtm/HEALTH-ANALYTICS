"""Production-safe reference bootstrap.

Alembic creates schema only. A fresh database also needs the approved, non-secret reference
configuration that every other command assumes: programmes, roles and their server-side
action permissions, the versioned indicator catalogue, the quality-rule catalogue, the
owner-approved population-period rules (D-045) and a neutral country root that the first
administrator can be scoped to.

What this module never creates: users, synthetic or real sub-national geography, DHIS2 UIDs
or mappings, raw observations, population values or boundary geometry. Indicator versions
are created without effective dates, so production keeps them unavailable until the owner
dates them or explicitly enables the governed undated fallback.

The bootstrap is idempotent. Rows that already match the approved reference are left alone;
missing rows are created; a row that exists but differs is reported as a conflict and nothing
is written, so hand-edited configuration is never silently overwritten. On PostgreSQL a
transaction-scoped advisory lock serialises concurrent release attempts.

OWNERSHIP. The bootstrap owns only these keyed rows and fields; everything else is owner-managed
configuration and is neither compared nor changed. Rows with other keys (a future programme,
role, indicator, quality rule or period rule) are ignored.

- programmes (key ``code`` in PROGRAMME_CATALOG): name, active, sensitive, first_release,
  description. Owner-managed: none.
- roles (key ``code`` in ROLE_CATALOG): name, is_active, exact permission set. Owner-managed:
  description.
- org_units (key ``UG``): name, level_type, parent_id (none), path, active. Owner-managed:
  valid_from, valid_to, ownership, facility_level.
- indicators (key ``code`` in INDICATOR_CATALOG): programme, name, active. Owner-managed:
  description.
- indicator_versions (key indicator + ``v1``): every INDICATOR_VERSION_FIELDS entry, and
  INDICATOR_VERSION_UNSET_FIELDS must stay unset; the indicator must have exactly one current
  version (v1 may be superseded by a later governed version). Owner-managed: valid_from and
  valid_to, the approved effective dates.
- quality_rules (key ``code`` + ``v1``): category, severity, explanation, enabled, normalised
  config.
- period_population_rules (key financial_year_key + programme scope): population_year,
  scope_kind, applies_to_period_kinds, approval_status, notes; a bootstrap-authored rule may not
  move to another programme scope.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.domain.enums import ActionPermission, ApprovalStatus, OrgUnitLevel, PeriodRuleScope, ProgrammeCode
from app.domain.formula_spec import validate_classification_spec, validate_formula_spec
from app.domain.indicator_catalog import INDICATOR_CATALOG, QUALITY_RULE_CATALOG
from app.models import (
    Indicator,
    IndicatorVersion,
    OrgUnit,
    PeriodPopulationRule,
    Programme,
    QualityRule,
    Role,
    RolePermission,
)
from app.services.geography import build_path

BOOTSTRAP_VERSION = "reference-bootstrap-v1"
# Arbitrary constant key for pg_advisory_xact_lock; only has to be unique within this database.
ADVISORY_LOCK_KEY = 4_815_162_342

ROOT_ORG_UNIT_CODE = "UG"
ROOT_ORG_UNIT_NAME = "Uganda"

PROGRAMME_CATALOG: tuple[tuple[str, str, bool], ...] = (
    (ProgrammeCode.MNCH.value, "Maternal, Newborn and Child Health", False),
    (ProgrammeCode.EPI.value, "Immunization / EPI", False),
    (ProgrammeCode.MPDSR.value, "MPDSR", True),
)
PROGRAMME_DESCRIPTION = "First-release programme. Future programmes are not seeded into navigation."

ROLE_CATALOG: dict[str, tuple[str, ...]] = {
    "national_analyst": (
        ActionPermission.VIEW.value,
        ActionPermission.EXPORT.value,
        ActionPermission.GENERATE_AI_REPORT.value,
    ),
    "regional_analyst": (
        ActionPermission.VIEW.value,
        ActionPermission.EXPORT.value,
        ActionPermission.GENERATE_AI_REPORT.value,
    ),
    "district_mch_focal": (
        ActionPermission.VIEW.value,
        ActionPermission.EXPORT.value,
        ActionPermission.GENERATE_AI_REPORT.value,
        ActionPermission.EDIT_POPULATION.value,
    ),
    "facility_user": (ActionPermission.VIEW.value,),
    "view_only": (ActionPermission.VIEW.value,),
    "mpdsr_analyst": (
        ActionPermission.VIEW.value,
        ActionPermission.EXPORT.value,
        ActionPermission.VIEW_MPDSR_EVENTS.value,
    ),
    "system_administrator": tuple(action.value for action in ActionPermission),
}

# Owner decision D-045 (2026-09-14), extending the FY-only scope of D-004: a financial year uses
# its first year, and the months, quarters and half-years inside it use the same base year.
FY_PERIOD_KINDS = ("fy", "fy_quarter", "quarter", "half", "month")
# The approved workbook covers 2024-2030. Later periods stay population_rule_missing.
POPULATION_SOURCE_FIRST_YEAR = 2024
POPULATION_SOURCE_LAST_YEAR = 2030
PERIOD_RULE_PROGRAMMES: tuple[str | None, ...] = (None, ProgrammeCode.MNCH.value)
FY_RULE_NOTE = "Owner decision D-045: FY base year, including its child periods."
CY_RULE_NOTE = "Owner decision D-045: calendar year N uses population year N."

QUALITY_RULE_VERSION = "v1"
INDICATOR_BASE_VERSION = "v1"

# Definitional fields of an indicator version. A difference in any of them is a conflict.
INDICATOR_VERSION_FIELDS = (
    "numerator_definition",
    "denominator_type",
    "denominator_coefficient",
    "multiplier",
    "unit",
    "display_precision",
    "direction",
    "target",
    "green_band",
    "yellow_band",
    "red_band",
    "blue_rule",
    "aggregation_method",
    "period_adjustment",
    "methodology_text",
    "formula_spec",
    "classification_spec",
)
# Fields the bootstrap leaves unset on the base version; a value there changes behaviour.
INDICATOR_VERSION_UNSET_FIELDS = ("denominator_reference_indicator_id", "quality_rules")


def quality_rule_config(code: str) -> dict | None:
    if code == "UNEXPECTED_ZERO":
        return {"require_prior_nonzero": True}
    if code == "ANOMALOUS_SPIKE_DROP":
        return {"ratio": 3.0}
    return None


def period_rule_specs() -> list[dict]:
    specs: list[dict] = []
    for start_year in range(POPULATION_SOURCE_FIRST_YEAR, POPULATION_SOURCE_LAST_YEAR):
        key = f"FY{start_year}/{str(start_year + 1)[2:]}"
        for programme in PERIOD_RULE_PROGRAMMES:
            specs.append(
                {
                    "financial_year_key": key,
                    "population_year": start_year,
                    "programme": programme,
                    "scope_kind": PeriodRuleScope.FINANCIAL_YEAR.value,
                    "applies_to_period_kinds": list(FY_PERIOD_KINDS),
                    "notes": FY_RULE_NOTE,
                }
            )
    for year in range(POPULATION_SOURCE_FIRST_YEAR, POPULATION_SOURCE_LAST_YEAR + 1):
        for programme in PERIOD_RULE_PROGRAMMES:
            specs.append(
                {
                    "financial_year_key": str(year),
                    "population_year": year,
                    "programme": programme,
                    "scope_kind": PeriodRuleScope.CALENDAR_YEAR.value,
                    "applies_to_period_kinds": ["year"],
                    "notes": CY_RULE_NOTE,
                }
            )
    return specs


class ReferenceBootstrapConflict(RuntimeError):
    """Existing configuration differs from the approved reference. Nothing was written."""

    def __init__(self, conflicts: list[str]) -> None:
        self.code = "reference_configuration_conflict"
        self.conflicts = conflicts
        super().__init__(f"{len(conflicts)} reference configuration conflict(s); nothing was written.")


@dataclass
class BootstrapReport:
    version: str = BOOTSTRAP_VERSION
    created: dict[str, int] = field(default_factory=dict)
    unchanged: dict[str, int] = field(default_factory=dict)
    dry_run: bool = False

    def count(self, kind: str, created: bool) -> None:
        bucket = self.created if created else self.unchanged
        bucket[kind] = bucket.get(kind, 0) + 1

    @property
    def changed(self) -> bool:
        return any(self.created.values())

    def as_dict(self) -> dict:
        return {
            "version": self.version,
            "dry_run": self.dry_run,
            "created": dict(sorted(self.created.items())),
            "unchanged": dict(sorted(self.unchanged.items())),
        }


def _lock(session: Session) -> None:
    if session.get_bind().dialect.name == "postgresql":
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": ADVISORY_LOCK_KEY})


def _normalise(value: object) -> object:
    """Canonical form for comparison: JSON-like values compare by content, not key order."""
    if isinstance(value, dict | list):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return value


def _differs(label: str, name: str, existing: object, expected: object, conflicts: list[str]) -> None:
    if _normalise(existing) != _normalise(expected):
        # Field names only. Stored values are never echoed: they may be operator-entered text.
        conflicts.append(f"{label}: {name} differs from the approved reference")


def role_name(code: str) -> str:
    return code.replace("_", " ").title()


def _inspect(session: Session) -> list[str]:
    """Compare every bootstrap-owned row and field with the approved reference. Read-only.

    Only keyed catalogue rows are inspected (see OWNERSHIP in the module docstring); rows with
    other keys are left alone, and owner-managed fields are never compared.
    """
    conflicts: list[str] = []

    programmes = {row.code: row for row in session.scalars(select(Programme)).all()}
    for code, name, sensitive in PROGRAMME_CATALOG:
        row = programmes.get(code)
        if row is None:
            continue
        label = f"programme {code}"
        for field_name, expected in (
            ("name", name),
            ("active", True),
            ("sensitive", sensitive),
            ("first_release", True),
            ("description", PROGRAMME_DESCRIPTION),
        ):
            _differs(label, field_name, getattr(row, field_name), expected, conflicts)

    roles = {row.code: row for row in session.scalars(select(Role)).all()}
    for code, actions in ROLE_CATALOG.items():
        role = roles.get(code)
        if role is None:
            continue
        label = f"role {code}"
        _differs(label, "name", role.name, role_name(code), conflicts)
        _differs(label, "is_active", role.is_active, True, conflicts)
        granted = session.scalars(select(RolePermission.action).where(RolePermission.role_id == role.id)).all()
        if sorted(granted) != sorted(actions):
            conflicts.append(f"{label}: permissions differ from the approved reference")

    root = session.scalar(select(OrgUnit).where(OrgUnit.code == ROOT_ORG_UNIT_CODE))
    if root is not None:
        label = f"org unit {ROOT_ORG_UNIT_CODE}"
        for field_name, expected in (
            ("name", ROOT_ORG_UNIT_NAME),
            ("level_type", OrgUnitLevel.COUNTRY.value),
            ("parent_id", None),
            ("path", build_path(None, ROOT_ORG_UNIT_CODE)),
            ("active", True),
        ):
            _differs(label, field_name, getattr(root, field_name), expected, conflicts)

    indicators = {row.code: row for row in session.scalars(select(Indicator)).all()}
    for spec in INDICATOR_CATALOG:
        indicator = indicators.get(spec["code"])
        if indicator is None:
            continue
        label = f"indicator {spec['code']}"
        programme = programmes.get(spec["programme"])
        _differs(label, "programme", indicator.programme_id, programme.id if programme else None, conflicts)
        _differs(label, "name", indicator.name, spec["name"], conflicts)
        _differs(label, "active", indicator.active, True, conflicts)
        versions = session.scalars(select(IndicatorVersion).where(IndicatorVersion.indicator_id == indicator.id)).all()
        base = next((row for row in versions if row.formula_version == INDICATOR_BASE_VERSION), None)
        if base is None:
            conflicts.append(f"{label}: catalogue version {INDICATOR_BASE_VERSION} is missing")
            continue
        version_label = f"{label} version {INDICATOR_BASE_VERSION}"
        for column in INDICATOR_VERSION_FIELDS:
            _differs(version_label, column, getattr(base, column), spec[column], conflicts)
        for column in INDICATOR_VERSION_UNSET_FIELDS:
            _differs(version_label, column, getattr(base, column), None, conflicts)
        # The base version may be superseded by a later governed version, but the indicator must
        # always have exactly one current version.
        current = [row for row in versions if row.is_current]
        if len(current) != 1:
            conflicts.append(f"{label}: is_current differs from the approved reference (one current version required)")

    rules = {(row.code, row.rule_version): row for row in session.scalars(select(QualityRule)).all()}
    for item in QUALITY_RULE_CATALOG:
        rule = rules.get((item["code"], QUALITY_RULE_VERSION))
        if rule is None:
            continue
        label = f"quality rule {item['code']} {QUALITY_RULE_VERSION}"
        for field_name, expected in (
            ("category", item["category"]),
            ("severity", item["severity"]),
            ("explanation", item["explanation"]),
            ("enabled", True),
            ("config", quality_rule_config(item["code"])),
        ):
            _differs(label, field_name, getattr(rule, field_name), expected, conflicts)

    programme_ids = {code: row.id for code, row in programmes.items()}
    governed_scopes = {programme_ids.get(code) if code else None for code in PERIOD_RULE_PROGRAMMES}
    governed_notes = {FY_RULE_NOTE, CY_RULE_NOTE}
    specs = period_rule_specs()
    governed_keys = {spec["financial_year_key"] for spec in specs}
    existing_rules = session.scalars(select(PeriodPopulationRule)).all()
    for spec in specs:
        programme_id = programme_ids.get(spec["programme"]) if spec["programme"] else None
        if spec["programme"] and programme_id is None:
            continue
        matches = [
            row
            for row in existing_rules
            if row.financial_year_key == spec["financial_year_key"] and row.programme_id == programme_id
        ]
        label = f"period rule {spec['financial_year_key']} ({spec['programme'] or 'all programmes'})"
        if len(matches) > 1:
            conflicts.append(f"{label}: duplicated")
            continue
        if not matches:
            continue
        row = matches[0]
        for field_name, existing, expected in (
            ("population_year", row.population_year, spec["population_year"]),
            ("scope_kind", row.scope_kind, spec["scope_kind"]),
            (
                "applies_to_period_kinds",
                sorted(row.applies_to_period_kinds or []),
                sorted(spec["applies_to_period_kinds"]),
            ),
            ("approval_status", row.approval_status, ApprovalStatus.APPROVED.value),
            ("notes", row.notes, spec["notes"]),
        ):
            _differs(label, field_name, existing, expected, conflicts)
    # A bootstrap-authored rule moved to a programme scope the reference does not use.
    for row in existing_rules:
        if (
            row.financial_year_key in governed_keys
            and row.notes in governed_notes
            and row.programme_id not in governed_scopes
        ):
            conflicts.append(
                f"period rule {row.financial_year_key}: programme scope differs from the approved reference"
            )
    return conflicts


def _ensure(session: Session, report: BootstrapReport) -> None:
    programmes = {row.code: row for row in session.scalars(select(Programme)).all()}
    for code, name, sensitive in PROGRAMME_CATALOG:
        created = code not in programmes
        if created:
            row = Programme(
                code=code,
                name=name,
                active=True,
                first_release=True,
                sensitive=sensitive,
                description=PROGRAMME_DESCRIPTION,
            )
            session.add(row)
            session.flush()
            programmes[code] = row
        report.count("programmes", created)

    roles = {row.code: row for row in session.scalars(select(Role)).all()}
    for code, actions in ROLE_CATALOG.items():
        created = code not in roles
        if created:
            role = Role(code=code, name=role_name(code), is_active=True)
            session.add(role)
            session.flush()
            for action in actions:
                session.add(RolePermission(role_id=role.id, action=action))
            roles[code] = role
        report.count("roles", created)

    root = session.scalar(select(OrgUnit).where(OrgUnit.code == ROOT_ORG_UNIT_CODE))
    if root is None:
        session.add(
            OrgUnit(
                code=ROOT_ORG_UNIT_CODE,
                name=ROOT_ORG_UNIT_NAME,
                level_type=OrgUnitLevel.COUNTRY.value,
                parent_id=None,
                path=build_path(None, ROOT_ORG_UNIT_CODE),
                active=True,
            )
        )
        session.flush()
    report.count("country_root", root is None)

    indicators = {row.code: row for row in session.scalars(select(Indicator)).all()}
    for spec in INDICATOR_CATALOG:
        created = spec["code"] not in indicators
        if created:
            validate_formula_spec(spec["formula_spec"])
            validate_classification_spec(spec["classification_spec"])
            indicator = Indicator(
                code=spec["code"], programme_id=programmes[spec["programme"]].id, name=spec["name"], active=True
            )
            session.add(indicator)
            session.flush()
            session.add(
                IndicatorVersion(
                    indicator_id=indicator.id,
                    formula_version=INDICATOR_BASE_VERSION,
                    # No valid_from: undated versions stay unavailable in production (D-041 register
                    # note) until the owner approves effective dates or the governed fallback.
                    is_current=True,
                    **{column: spec[column] for column in INDICATOR_VERSION_FIELDS},
                )
            )
        report.count("indicators", created)

    rules = {(row.code, row.rule_version) for row in session.scalars(select(QualityRule)).all()}
    for item in QUALITY_RULE_CATALOG:
        created = (item["code"], QUALITY_RULE_VERSION) not in rules
        if created:
            session.add(
                QualityRule(
                    code=item["code"],
                    category=item["category"],
                    severity=item["severity"],
                    explanation=item["explanation"],
                    rule_version=QUALITY_RULE_VERSION,
                    enabled=True,
                    config=quality_rule_config(item["code"]),
                )
            )
        report.count("quality_rules", created)

    existing_rules = {
        (row.financial_year_key, row.programme_id) for row in session.scalars(select(PeriodPopulationRule)).all()
    }
    for spec in period_rule_specs():
        programme_id = programmes[spec["programme"]].id if spec["programme"] else None
        created = (spec["financial_year_key"], programme_id) not in existing_rules
        if created:
            session.add(
                PeriodPopulationRule(
                    financial_year_key=spec["financial_year_key"],
                    population_year=spec["population_year"],
                    programme_id=programme_id,
                    scope_kind=spec["scope_kind"],
                    applies_to_period_kinds=spec["applies_to_period_kinds"],
                    approval_status=ApprovalStatus.APPROVED.value,
                    notes=spec["notes"],
                )
            )
        report.count("period_rules", created)
    session.flush()


def bootstrap_reference_data(session: Session, *, dry_run: bool = False) -> BootstrapReport:
    """Create missing approved reference rows. Raises ReferenceBootstrapConflict on any mismatch.

    The caller owns the transaction: commit after a successful call, roll back otherwise. With
    ``dry_run`` every change is rolled back before returning.
    """
    _lock(session)
    conflicts = _inspect(session)
    if conflicts:
        raise ReferenceBootstrapConflict(conflicts)
    report = BootstrapReport(dry_run=dry_run)
    _ensure(session, report)
    if dry_run:
        session.rollback()
    return report

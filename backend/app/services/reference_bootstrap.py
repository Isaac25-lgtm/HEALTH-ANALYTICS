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
"""

from __future__ import annotations

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


def _differs(label: str, name: str, existing: object, expected: object, conflicts: list[str]) -> None:
    if existing != expected:
        conflicts.append(f"{label}: {name} differs from the approved reference")


def _inspect(session: Session) -> list[str]:
    """Compare every existing reference row with the approved reference. Read-only."""
    conflicts: list[str] = []

    programmes = {row.code: row for row in session.scalars(select(Programme)).all()}
    for code, name, sensitive in PROGRAMME_CATALOG:
        row = programmes.get(code)
        if row is None:
            continue
        _differs(f"programme {code}", "sensitive", row.sensitive, sensitive, conflicts)
        _differs(f"programme {code}", "name", row.name, name, conflicts)
        if not row.active:
            conflicts.append(f"programme {code}: exists but is inactive")

    roles = {row.code: row for row in session.scalars(select(Role)).all()}
    for code, actions in ROLE_CATALOG.items():
        role = roles.get(code)
        if role is None:
            continue
        granted = set(session.scalars(select(RolePermission.action).where(RolePermission.role_id == role.id)).all())
        if granted != set(actions):
            missing = sorted(set(actions) - granted)
            extra = sorted(granted - set(actions))
            conflicts.append(f"role {code}: permissions differ (missing={missing}, extra={extra})")

    root = session.scalar(select(OrgUnit).where(OrgUnit.code == ROOT_ORG_UNIT_CODE))
    if root is not None:
        if root.parent_id is not None:
            conflicts.append(f"org unit {ROOT_ORG_UNIT_CODE}: exists but is not a root unit")
        _differs(f"org unit {ROOT_ORG_UNIT_CODE}", "level_type", root.level_type, OrgUnitLevel.COUNTRY.value, conflicts)
        if not root.active:
            conflicts.append(f"org unit {ROOT_ORG_UNIT_CODE}: exists but is inactive")
    other_countries = session.scalars(
        select(OrgUnit.code).where(
            OrgUnit.parent_id.is_(None),
            OrgUnit.level_type == OrgUnitLevel.COUNTRY.value,
            OrgUnit.code != ROOT_ORG_UNIT_CODE,
        )
    ).all()
    if other_countries:
        conflicts.append(f"org units: another country root exists ({sorted(other_countries)})")

    indicators = {row.code: row for row in session.scalars(select(Indicator)).all()}
    for spec in INDICATOR_CATALOG:
        indicator = indicators.get(spec["code"])
        if indicator is None:
            continue
        label = f"indicator {spec['code']}"
        programme = programmes.get(spec["programme"])
        if programme is None or indicator.programme_id != programme.id:
            conflicts.append(f"{label}: belongs to a different programme")
        version = session.scalar(
            select(IndicatorVersion).where(
                IndicatorVersion.indicator_id == indicator.id,
                IndicatorVersion.formula_version == INDICATOR_BASE_VERSION,
            )
        )
        if version is None:
            conflicts.append(f"{label}: exists without catalogue version {INDICATOR_BASE_VERSION}")
            continue
        for column in INDICATOR_VERSION_FIELDS:
            _differs(label, column, getattr(version, column), spec[column], conflicts)

    rules = {(row.code, row.rule_version): row for row in session.scalars(select(QualityRule)).all()}
    for item in QUALITY_RULE_CATALOG:
        rule = rules.get((item["code"], QUALITY_RULE_VERSION))
        if rule is None:
            continue
        label = f"quality rule {item['code']}"
        _differs(label, "category", rule.category, item["category"], conflicts)
        _differs(label, "severity", rule.severity, item["severity"], conflicts)

    programme_ids = {code: row.id for code, row in programmes.items()}
    existing_rules = session.scalars(select(PeriodPopulationRule)).all()
    for spec in period_rule_specs():
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
        _differs(label, "population_year", row.population_year, spec["population_year"], conflicts)
        _differs(label, "scope_kind", row.scope_kind, spec["scope_kind"], conflicts)
        _differs(
            label,
            "applies_to_period_kinds",
            sorted(row.applies_to_period_kinds or []),
            sorted(spec["applies_to_period_kinds"]),
            conflicts,
        )
        _differs(label, "approval_status", row.approval_status, ApprovalStatus.APPROVED.value, conflicts)
    return conflicts


def _ensure(session: Session, report: BootstrapReport) -> None:
    programmes = {row.code: row for row in session.scalars(select(Programme)).all()}
    for code, name, sensitive in PROGRAMME_CATALOG:
        created = code not in programmes
        if created:
            row = Programme(
                code=code,
                name=name,
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
            role = Role(code=code, name=code.replace("_", " ").title())
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
            indicator = Indicator(code=spec["code"], programme_id=programmes[spec["programme"]].id, name=spec["name"])
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

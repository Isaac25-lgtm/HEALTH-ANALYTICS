"""Drift mutations for the reference bootstrap, shared by the SQLite and PostgreSQL tests.

Each mutation changes one bootstrap-owned field (or the permission set) in a database that the
bootstrap has already populated, and knows how to undo itself so one PostgreSQL database can be
reused for every case. Mutated text values carry SENTINEL so tests can prove stored values never
appear in conflict messages.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import MetaData, and_, delete, insert, select, update
from sqlalchemy.engine import Connection, Engine

SENTINEL = "SENTINEL-7731-OPERATOR-TEXT"


@dataclass(frozen=True)
class Mutation:
    id: str
    table: str
    where: Callable[[MetaData, Connection], object]
    column: str
    value: Callable[[MetaData, Connection], object]
    expected: str


def _code(table: str, code: str):
    return lambda meta, conn: meta.tables[table].c.code == code


def _const(value):
    return lambda meta, conn: value


def _indicator_id(conn: Connection, meta: MetaData, code: str):
    table = meta.tables["indicators"]
    return conn.execute(select(table.c.id).where(table.c.code == code)).scalar_one()


def _version_where(code: str):
    def where(meta, conn):
        versions = meta.tables["indicator_versions"]
        return and_(versions.c.indicator_id == _indicator_id(conn, meta, code), versions.c.formula_version == "v1")

    return where


def _period_where(key: str, programme: str | None):
    def where(meta, conn):
        rules = meta.tables["period_population_rules"]
        if programme is None:
            return and_(rules.c.financial_year_key == key, rules.c.programme_id.is_(None))
        programmes = meta.tables["programmes"]
        programme_id = conn.execute(select(programmes.c.id).where(programmes.c.code == programme)).scalar_one()
        return and_(rules.c.financial_year_key == key, rules.c.programme_id == programme_id)

    return where


def _programme_id(code: str):
    def value(meta, conn):
        programmes = meta.tables["programmes"]
        return conn.execute(select(programmes.c.id).where(programmes.c.code == code)).scalar_one()

    return value


def _quality_where(code: str):
    return lambda meta, conn: and_(
        meta.tables["quality_rules"].c.code == code, meta.tables["quality_rules"].c.rule_version == "v1"
    )


MUTATIONS: list[Mutation] = [
    Mutation(
        "programme-name", "programmes", _code("programmes", "EPI"), "name", _const(SENTINEL), "programme EPI: name"
    ),
    Mutation(
        "programme-active", "programmes", _code("programmes", "MNCH"), "active", _const(False), "programme MNCH: active"
    ),
    Mutation(
        "programme-sensitive",
        "programmes",
        _code("programmes", "MPDSR"),
        "sensitive",
        _const(False),
        "programme MPDSR: sensitive",
    ),
    Mutation(
        "programme-first-release",
        "programmes",
        _code("programmes", "EPI"),
        "first_release",
        _const(False),
        "programme EPI: first_release",
    ),
    Mutation(
        "programme-description",
        "programmes",
        _code("programmes", "EPI"),
        "description",
        _const(SENTINEL),
        "programme EPI: description",
    ),
    Mutation(
        "role-inactive-admin",
        "roles",
        _code("roles", "system_administrator"),
        "is_active",
        _const(False),
        "role system_administrator: is_active",
    ),
    Mutation("role-name", "roles", _code("roles", "view_only"), "name", _const(SENTINEL), "role view_only: name"),
    Mutation("root-name", "org_units", _code("org_units", "UG"), "name", _const(SENTINEL), "org unit UG: name"),
    Mutation(
        "root-path", "org_units", _code("org_units", "UG"), "path", _const("/UG-" + SENTINEL), "org unit UG: path"
    ),
    Mutation(
        "root-level", "org_units", _code("org_units", "UG"), "level_type", _const("region"), "org unit UG: level_type"
    ),
    Mutation("root-active", "org_units", _code("org_units", "UG"), "active", _const(False), "org unit UG: active"),
    Mutation(
        "indicator-name",
        "indicators",
        _code("indicators", "ANC1_COVERAGE"),
        "name",
        _const(SENTINEL),
        "indicator ANC1_COVERAGE: name",
    ),
    Mutation(
        "indicator-inactive",
        "indicators",
        _code("indicators", "ANC1_COVERAGE"),
        "active",
        _const(False),
        "indicator ANC1_COVERAGE: active",
    ),
    Mutation(
        "indicator-programme",
        "indicators",
        _code("indicators", "ANC1_COVERAGE"),
        "programme_id",
        _programme_id("EPI"),
        "indicator ANC1_COVERAGE: programme",
    ),
    Mutation(
        "version-target",
        "indicator_versions",
        _version_where("ANC1_COVERAGE"),
        "target",
        _const(SENTINEL),
        "indicator ANC1_COVERAGE version v1: target",
    ),
    Mutation(
        "version-formula",
        "indicator_versions",
        _version_where("ANC1_COVERAGE"),
        "formula_spec",
        _const({"kind": "ratio", "note": SENTINEL}),
        "indicator ANC1_COVERAGE version v1: formula_spec",
    ),
    Mutation(
        "version-not-current",
        "indicator_versions",
        _version_where("ANC1_COVERAGE"),
        "is_current",
        _const(False),
        "indicator ANC1_COVERAGE: is_current",
    ),
    Mutation(
        "version-quality-rules",
        "indicator_versions",
        _version_where("ANC1_COVERAGE"),
        "quality_rules",
        _const({"override": SENTINEL}),
        "indicator ANC1_COVERAGE version v1: quality_rules",
    ),
    Mutation(
        "quality-disabled",
        "quality_rules",
        _quality_where("UNEXPECTED_ZERO"),
        "enabled",
        _const(False),
        "quality rule UNEXPECTED_ZERO v1: enabled",
    ),
    Mutation(
        "quality-config",
        "quality_rules",
        _quality_where("ANOMALOUS_SPIKE_DROP"),
        "config",
        _const({"ratio": 99.5}),
        "quality rule ANOMALOUS_SPIKE_DROP v1: config",
    ),
    Mutation(
        "quality-explanation",
        "quality_rules",
        _quality_where("UNEXPECTED_ZERO"),
        "explanation",
        _const(SENTINEL),
        "quality rule UNEXPECTED_ZERO v1: explanation",
    ),
    Mutation(
        "quality-severity",
        "quality_rules",
        _quality_where("UNEXPECTED_ZERO"),
        "severity",
        _const("info"),
        "quality rule UNEXPECTED_ZERO v1: severity",
    ),
    Mutation(
        "period-year",
        "period_population_rules",
        _period_where("FY2025/26", None),
        "population_year",
        _const(2026),
        "period rule FY2025/26 (all programmes): population_year",
    ),
    Mutation(
        "period-scope-kind",
        "period_population_rules",
        _period_where("FY2025/26", None),
        "scope_kind",
        _const("calendar_year"),
        "period rule FY2025/26 (all programmes): scope_kind",
    ),
    Mutation(
        "period-approval",
        "period_population_rules",
        _period_where("FY2025/26", "MNCH"),
        "approval_status",
        _const("draft"),
        "period rule FY2025/26 (MNCH): approval_status",
    ),
    Mutation(
        "period-kinds",
        "period_population_rules",
        _period_where("2026", None),
        "applies_to_period_kinds",
        _const(["year", "month"]),
        "period rule 2026 (all programmes): applies_to_period_kinds",
    ),
    Mutation(
        "period-notes",
        "period_population_rules",
        _period_where("2026", None),
        "notes",
        _const(SENTINEL),
        "period rule 2026 (all programmes): notes",
    ),
    Mutation(
        "period-programme-scope",
        "period_population_rules",
        _period_where("FY2026/27", "MNCH"),
        "programme_id",
        _programme_id("EPI"),
        "period rule FY2026/27: programme scope",
    ),
]

SPECIAL = ("role-extra-permission",)
ALL_IDS = [mutation.id for mutation in MUTATIONS] + list(SPECIAL)


def reflect(engine: Engine) -> MetaData:
    meta = MetaData()
    meta.reflect(bind=engine)
    return meta


def apply(engine: Engine, mutation_id: str) -> Callable[[], None]:
    """Apply one mutation and return a function that restores the original state."""
    meta = reflect(engine)
    if mutation_id == "role-extra-permission":
        roles, permissions = meta.tables["roles"], meta.tables["role_permissions"]
        row_id = uuid4()
        with engine.begin() as conn:
            role_id = conn.execute(select(roles.c.id).where(roles.c.code == "view_only")).scalar_one()
            conn.execute(insert(permissions).values(id=_ident(engine, row_id), role_id=role_id, action="manage_users"))

        def undo() -> None:
            with engine.begin() as conn:
                conn.execute(delete(permissions).where(permissions.c.id == _ident(engine, row_id)))

        return undo
    mutation = next(item for item in MUTATIONS if item.id == mutation_id)
    table = meta.tables[mutation.table]
    column = table.c[mutation.column]
    with engine.begin() as conn:
        where = mutation.where(meta, conn)
        original = conn.execute(select(column).where(where)).scalar_one()
        new_value = mutation.value(meta, conn)
        conn.execute(update(table).where(where).values({mutation.column: new_value}))

    def restore() -> None:
        with engine.begin() as conn:
            current_where = (
                mutation.where(meta, conn)
                if mutation.column != "programme_id"
                else _moved_where(meta, conn, mutation, new_value)
            )
            conn.execute(update(table).where(current_where).values({mutation.column: original}))

    return restore


def _moved_where(meta: MetaData, conn: Connection, mutation: Mutation, new_value):
    table = meta.tables[mutation.table]
    if mutation.table == "indicators":
        return table.c.code == "ANC1_COVERAGE"
    return and_(table.c.financial_year_key == "FY2026/27", table.c.programme_id == new_value)


def _ident(engine: Engine, value):
    return value.hex if engine.dialect.name == "sqlite" else value


def expected_fragment(mutation_id: str) -> str:
    if mutation_id == "role-extra-permission":
        return "role view_only: permissions differ"
    return next(item.expected for item in MUTATIONS if item.id == mutation_id)


def remove_one_missing_row(engine: Engine) -> Callable[[], int]:
    """Delete one catalogue row the bootstrap would recreate; return a counter of that key."""
    meta = reflect(engine)
    rules = meta.tables["quality_rules"]
    with engine.begin() as conn:
        conn.execute(delete(rules).where(and_(rules.c.code == "MISSING_CAUSE", rules.c.rule_version == "v1")))

    def count() -> int:
        with engine.connect() as conn:
            return len(conn.execute(select(rules.c.id).where(rules.c.code == "MISSING_CAUSE")).all())

    return count

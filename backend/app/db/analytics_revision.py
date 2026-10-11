"""Transactional invalidation for prepared analytical products (no source data copied)."""

REVISION_TABLES = (
    "raw_aggregate_values",
    "raw_event_snapshots",
    "sync_jobs",
    "indicators",
    "indicator_versions",
    "source_mappings",
    "event_field_mappings",
    "period_population_rules",
    "population_versions",
    "population_values",
    "population_source_aliases",
    "facility_population_entries",
    "org_units",
    "org_unit_mappings",
    "geometries",
    "quality_rules",
    "programmes",
)

# Tables that are configuration rather than source data. A change to one of them moves the
# "config" revision as well as the global one (migration 0020); source rows, events and
# synchronisation jobs move only the global one.
CONFIG_TABLES = frozenset(REVISION_TABLES) - {"raw_aggregate_values", "raw_event_snapshots", "sync_jobs"}

_BUMP = "UPDATE analytics_revisions SET revision = revision + 1 WHERE key = 'global';"
_BUMP_CONFIG = "UPDATE analytics_revisions SET revision = revision + 1 WHERE key IN ('global', 'config');"
# PostgreSQL: one bump per statement that changed at least one row (migration 0017). A bump per
# row made a bulk write update the single revision row once per row inside one transaction.
_PG_FUNCTIONS = {
    "hpip_bump_revision_new": "EXISTS (SELECT 1 FROM hpip_new)",
    "hpip_bump_revision_old": "EXISTS (SELECT 1 FROM hpip_old)",
    "hpip_bump_config_new": "EXISTS (SELECT 1 FROM hpip_new)",
    "hpip_bump_config_old": "EXISTS (SELECT 1 FROM hpip_old)",
    "hpip_bump_revision_jobs_new": "EXISTS (SELECT 1 FROM hpip_new WHERE status = 'succeeded')",
    "hpip_bump_revision_jobs_old": "EXISTS (SELECT 1 FROM hpip_old WHERE status = 'succeeded')",
    "hpip_bump_revision_jobs_both": (
        "EXISTS (SELECT 1 FROM hpip_new WHERE status = 'succeeded') "
        "OR EXISTS (SELECT 1 FROM hpip_old WHERE status = 'succeeded')"
    ),
}
_PG_REFERENCING = {
    "INSERT": "REFERENCING NEW TABLE AS hpip_new",
    "UPDATE": "REFERENCING OLD TABLE AS hpip_old NEW TABLE AS hpip_new",
    "DELETE": "REFERENCING OLD TABLE AS hpip_old",
}


def _pg_function_for(table: str, action: str) -> str:
    if table == "sync_jobs":
        return {
            "INSERT": "hpip_bump_revision_jobs_new",
            "UPDATE": "hpip_bump_revision_jobs_both",
            "DELETE": "hpip_bump_revision_jobs_old",
        }[action]
    kind = "config" if table in CONFIG_TABLES else "revision"
    return f"hpip_bump_{kind}_old" if action == "DELETE" else f"hpip_bump_{kind}_new"


def install_revision_triggers(_metadata, connection, **_kwargs) -> None:
    """For explicit create_all test databases. Production uses frozen migrations 0015 and 0017."""
    if connection.dialect.name not in {"sqlite", "postgresql"}:
        return
    connection.exec_driver_sql(
        "INSERT INTO analytics_revisions (key, revision) VALUES ('global', 0), ('config', 0) "
        "ON CONFLICT (key) DO NOTHING"
    )
    if connection.dialect.name == "postgresql":
        for name, condition in _PG_FUNCTIONS.items():
            bump = _BUMP_CONFIG if "_config_" in name else _BUMP
            connection.exec_driver_sql(
                f"CREATE OR REPLACE FUNCTION {name}() RETURNS trigger LANGUAGE plpgsql AS $$ "
                f"BEGIN IF {condition} THEN {bump} END IF; RETURN NULL; END $$"
            )
    for table in REVISION_TABLES:
        for action in ("INSERT", "UPDATE", "DELETE"):
            name = f"hpip_rev_{table}_{action.lower()}"
            if connection.dialect.name == "sqlite":
                when = ""
                if table == "sync_jobs":
                    condition = {
                        "INSERT": "NEW.status = 'succeeded'",
                        "DELETE": "OLD.status = 'succeeded'",
                        "UPDATE": "NEW.status = 'succeeded' OR OLD.status = 'succeeded'",
                    }[action]
                    when = f" WHEN ({condition})"
                bump = _BUMP_CONFIG if table in CONFIG_TABLES else _BUMP
                connection.exec_driver_sql(
                    f"CREATE TRIGGER IF NOT EXISTS {name} AFTER {action} ON {table}{when} BEGIN {bump} END"
                )
            else:
                connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS {name} ON {table}")
                connection.exec_driver_sql(
                    f"CREATE TRIGGER {name} AFTER {action} ON {table} {_PG_REFERENCING[action]} "
                    f"FOR EACH STATEMENT EXECUTE FUNCTION {_pg_function_for(table, action)}()"
                )

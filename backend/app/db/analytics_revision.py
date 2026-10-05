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


def install_revision_triggers(_metadata, connection, **_kwargs) -> None:
    """For explicit create_all test databases. Production uses frozen migration 0015."""
    if connection.dialect.name not in {"sqlite", "postgresql"}:
        return
    connection.exec_driver_sql(
        "INSERT INTO analytics_revisions (key, revision) VALUES ('global', 0) ON CONFLICT (key) DO NOTHING"
    )
    if connection.dialect.name == "postgresql":
        connection.exec_driver_sql("""CREATE OR REPLACE FUNCTION hpip_bump_analytics_revision() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN UPDATE analytics_revisions SET revision = revision + 1
        WHERE key = 'global'; RETURN NULL; END $$""")
    for table in REVISION_TABLES:
        for action in ("INSERT", "UPDATE", "DELETE"):
            name = f"hpip_rev_{table}_{action.lower()}"
            when = ""
            if table == "sync_jobs":
                condition = {
                    "INSERT": "NEW.status = 'succeeded'",
                    "DELETE": "OLD.status = 'succeeded'",
                    "UPDATE": "NEW.status = 'succeeded' OR OLD.status = 'succeeded'",
                }[action]
                when = f" WHEN ({condition})"
            if connection.dialect.name == "sqlite":
                connection.exec_driver_sql(f"""CREATE TRIGGER IF NOT EXISTS {name} AFTER {action} ON {table}{when}
                BEGIN UPDATE analytics_revisions SET revision = revision + 1 WHERE key = 'global'; END""")
            else:
                connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS {name} ON {table}")
                connection.exec_driver_sql(
                    f"CREATE TRIGGER {name} AFTER {action} ON {table} FOR EACH ROW{when} "
                    "EXECUTE FUNCTION hpip_bump_analytics_revision()"
                )

"""Record explicit extraction coverage, without reconstructing undocumented old jobs.

Revision ID: 0015_sync_coverage_manifest
Revises: 0014_calculation_run_reuse
"""

import sqlalchemy as sa
from alembic import op

revision = "0015_sync_coverage_manifest"
down_revision = "0014_calculation_run_reuse"
branch_labels = None
depends_on = None

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


def upgrade() -> None:
    op.add_column("sync_jobs", sa.Column("coverage_manifest", sa.JSON(), nullable=True))
    condition = sa.text(
        "job_type = 'aggregate_facilities' AND status IN ('queued', 'running') AND idempotency_key IS NOT NULL"
    )
    op.create_index(
        "uq_active_facility_sync_key",
        "sync_jobs",
        ["idempotency_key"],
        unique=True,
        sqlite_where=condition,
        postgresql_where=condition,
    )
    op.create_table(
        "analytics_revisions",
        sa.Column("key", sa.String(40), primary_key=True),
        sa.Column("revision", sa.BigInteger(), nullable=False),
    )
    op.create_index(
        "ix_analysis_snapshots_prepared_lookup",
        "analysis_snapshots",
        ["user_id", "org_unit_id", "period", "module", "status", "created_at"],
    )
    op.execute("INSERT INTO analytics_revisions (key, revision) VALUES ('global', 0)")
    postgres = op.get_bind().dialect.name == "postgresql"
    if postgres:
        op.execute("""CREATE FUNCTION hpip_bump_analytics_revision() RETURNS trigger LANGUAGE plpgsql
        AS $$ BEGIN UPDATE analytics_revisions SET revision = revision + 1 WHERE key = 'global';
        RETURN NULL; END $$""")
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
            if postgres:
                op.execute(
                    f"CREATE TRIGGER {name} AFTER {action} ON {table} FOR EACH ROW{when} "
                    "EXECUTE FUNCTION hpip_bump_analytics_revision()"
                )
            else:
                op.execute(
                    f"CREATE TRIGGER {name} AFTER {action} ON {table}{when} BEGIN "
                    "UPDATE analytics_revisions SET revision = revision + 1 WHERE key = 'global'; END"
                )


def downgrade() -> None:
    postgres = op.get_bind().dialect.name == "postgresql"
    for table in REVISION_TABLES:
        for action in ("INSERT", "UPDATE", "DELETE"):
            name = f"hpip_rev_{table}_{action.lower()}"
            op.execute(f"DROP TRIGGER IF EXISTS {name}" + (f" ON {table}" if postgres else ""))
    if postgres:
        op.execute("DROP FUNCTION hpip_bump_analytics_revision()")
    op.drop_table("analytics_revisions")
    op.drop_index("ix_analysis_snapshots_prepared_lookup", table_name="analysis_snapshots")
    op.drop_index("uq_active_facility_sync_key", table_name="sync_jobs")
    op.drop_column("sync_jobs", "coverage_manifest")

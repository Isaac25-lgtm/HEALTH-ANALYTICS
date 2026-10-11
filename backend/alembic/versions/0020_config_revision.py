"""Tell configuration changes apart from source-data changes, and let a run carry its fingerprint.

The global analytics revision moves for any change, including facility rows loaded on demand for
one district. A second counter, ``config``, moves only when a non-source table changes (indicators,
mappings, populations, organisation units, geometries, rules). A stored run whose configuration
revision is unchanged can then be re-verified from an exact fingerprint of its own source rows.

Revision ID: 0020_config_revision
Revises: 0019_snapshot_timestamps
"""

import sqlalchemy as sa
from alembic import op

revision = "0020_config_revision"
down_revision = "0019_snapshot_timestamps"
branch_labels = None
depends_on = None

CONFIG_TABLES = (
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
_BOTH = "UPDATE analytics_revisions SET revision = revision + 1 WHERE key IN ('global', 'config');"
_GLOBAL = "UPDATE analytics_revisions SET revision = revision + 1 WHERE key = 'global';"
_REFERENCING = {
    "INSERT": "REFERENCING NEW TABLE AS hpip_new",
    "UPDATE": "REFERENCING OLD TABLE AS hpip_old NEW TABLE AS hpip_new",
    "DELETE": "REFERENCING OLD TABLE AS hpip_old",
}


def upgrade() -> None:
    op.add_column("calculation_run_memos", sa.Column("config_revision", sa.BigInteger(), nullable=True))
    op.add_column("calculation_run_memos", sa.Column("inputs_digest", sa.String(64), nullable=True))
    op.create_table(
        "rollup_states",
        sa.Column("period", sa.String(40), primary_key=True),
        sa.Column("revision", sa.BigInteger(), nullable=True),
        sa.Column("summable_digest", sa.String(64), nullable=True),
        sa.Column("units", sa.JSON(), nullable=True),
        sa.Column("jobs", sa.JSON(), nullable=True),
    )
    # Roll-up verification markers briefly lived in analytics_revisions; the state table replaces them.
    op.execute("DELETE FROM analytics_revisions WHERE key LIKE 'rollup%'")
    op.execute("INSERT INTO analytics_revisions (key, revision) VALUES ('config', 0)")
    postgres = op.get_bind().dialect.name == "postgresql"
    if postgres:
        for name, table in (("hpip_bump_config_new", "hpip_new"), ("hpip_bump_config_old", "hpip_old")):
            op.execute(
                f"CREATE OR REPLACE FUNCTION {name}() RETURNS trigger LANGUAGE plpgsql AS $$ "
                f"BEGIN IF EXISTS (SELECT 1 FROM {table}) THEN {_BOTH} END IF; RETURN NULL; END $$"
            )
    for table in CONFIG_TABLES:
        for action in ("INSERT", "UPDATE", "DELETE"):
            name = f"hpip_rev_{table}_{action.lower()}"
            if postgres:
                function = "hpip_bump_config_old" if action == "DELETE" else "hpip_bump_config_new"
                op.execute(f"DROP TRIGGER IF EXISTS {name} ON {table}")
                op.execute(
                    f"CREATE TRIGGER {name} AFTER {action} ON {table} {_REFERENCING[action]} "
                    f"FOR EACH STATEMENT EXECUTE FUNCTION {function}()"
                )
            else:
                op.execute(f"DROP TRIGGER IF EXISTS {name}")
                op.execute(f"CREATE TRIGGER {name} AFTER {action} ON {table} BEGIN {_BOTH} END")


def downgrade() -> None:
    postgres = op.get_bind().dialect.name == "postgresql"
    for table in CONFIG_TABLES:
        for action in ("INSERT", "UPDATE", "DELETE"):
            name = f"hpip_rev_{table}_{action.lower()}"
            if postgres:
                function = "hpip_bump_revision_old" if action == "DELETE" else "hpip_bump_revision_new"
                op.execute(f"DROP TRIGGER IF EXISTS {name} ON {table}")
                op.execute(
                    f"CREATE TRIGGER {name} AFTER {action} ON {table} {_REFERENCING[action]} "
                    f"FOR EACH STATEMENT EXECUTE FUNCTION {function}()"
                )
            else:
                op.execute(f"DROP TRIGGER IF EXISTS {name}")
                op.execute(f"CREATE TRIGGER {name} AFTER {action} ON {table} BEGIN {_GLOBAL} END")
    if postgres:
        op.execute("DROP FUNCTION IF EXISTS hpip_bump_config_new()")
        op.execute("DROP FUNCTION IF EXISTS hpip_bump_config_old()")
    op.execute("DELETE FROM analytics_revisions WHERE key = 'config'")
    op.drop_table("rollup_states")
    op.drop_column("calculation_run_memos", "inputs_digest")
    op.drop_column("calculation_run_memos", "config_revision")

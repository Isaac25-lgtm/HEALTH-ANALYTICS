"""Bump the analytics revision once per changing statement instead of once per row.

A bulk write of N rows used to update the single revision row N times inside one transaction.
PostgreSQL keeps every one of those versions until commit, so each further update walks a longer
chain: a national event refresh spent over an hour there and blocked every other writer meanwhile.
Statement-level triggers with transition tables keep the same meaning (any statement that changes
at least one row bumps the revision) at one bump per statement. SQLite keeps its row triggers.

Revision ID: 0017_statement_revision_triggers
Revises: 0016_calculation_run_memos
"""

from alembic import op

revision = "0017_statement_revision_triggers"
down_revision = "0016_calculation_run_memos"
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

_BUMP = "UPDATE analytics_revisions SET revision = revision + 1 WHERE key = 'global';"
_FUNCTIONS = {
    "hpip_bump_revision_new": "EXISTS (SELECT 1 FROM hpip_new)",
    "hpip_bump_revision_old": "EXISTS (SELECT 1 FROM hpip_old)",
    "hpip_bump_revision_jobs_new": "EXISTS (SELECT 1 FROM hpip_new WHERE status = 'succeeded')",
    "hpip_bump_revision_jobs_old": "EXISTS (SELECT 1 FROM hpip_old WHERE status = 'succeeded')",
    "hpip_bump_revision_jobs_both": (
        "EXISTS (SELECT 1 FROM hpip_new WHERE status = 'succeeded') "
        "OR EXISTS (SELECT 1 FROM hpip_old WHERE status = 'succeeded')"
    ),
}
_REFERENCING = {
    "INSERT": "REFERENCING NEW TABLE AS hpip_new",
    "UPDATE": "REFERENCING OLD TABLE AS hpip_old NEW TABLE AS hpip_new",
    "DELETE": "REFERENCING OLD TABLE AS hpip_old",
}


def _function_for(table: str, action: str) -> str:
    if table == "sync_jobs":
        return {
            "INSERT": "hpip_bump_revision_jobs_new",
            "UPDATE": "hpip_bump_revision_jobs_both",
            "DELETE": "hpip_bump_revision_jobs_old",
        }[action]
    return "hpip_bump_revision_old" if action == "DELETE" else "hpip_bump_revision_new"


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for name, condition in _FUNCTIONS.items():
        op.execute(
            f"CREATE OR REPLACE FUNCTION {name}() RETURNS trigger LANGUAGE plpgsql AS $$ "
            f"BEGIN IF {condition} THEN {_BUMP} END IF; RETURN NULL; END $$"
        )
    for table in REVISION_TABLES:
        for action in ("INSERT", "UPDATE", "DELETE"):
            name = f"hpip_rev_{table}_{action.lower()}"
            op.execute(f"DROP TRIGGER IF EXISTS {name} ON {table}")
            op.execute(
                f"CREATE TRIGGER {name} AFTER {action} ON {table} {_REFERENCING[action]} "
                f"FOR EACH STATEMENT EXECUTE FUNCTION {_function_for(table, action)}()"
            )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
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
            op.execute(f"DROP TRIGGER IF EXISTS {name} ON {table}")
            op.execute(
                f"CREATE TRIGGER {name} AFTER {action} ON {table} FOR EACH ROW{when} "
                "EXECUTE FUNCTION hpip_bump_analytics_revision()"
            )
    for name in _FUNCTIONS:
        op.execute(f"DROP FUNCTION IF EXISTS {name}()")

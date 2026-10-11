"""Give two tables the row timestamps their models have always declared.

Revision 0006 (analysis_snapshots) and the population alias table created ``created_at`` and
``updated_at`` without a default or NOT NULL. Every snapshot was therefore stored with an empty
creation time: "latest snapshot" ordering was arbitrary and the retention purge, which selects by
creation time, never removed one. Existing rows are backfilled (a snapshot from its own recorded
generation time) and PostgreSQL then enforces the default and NOT NULL. SQLite cannot alter a
column in place; it is backfilled only (SQLite databases are built from the models in tests).

Revision ID: 0019_snapshot_timestamps
Revises: 0018_run_memo_validity
"""

import sqlalchemy as sa
from alembic import op

revision = "0019_snapshot_timestamps"
down_revision = "0018_run_memo_validity"
branch_labels = None
depends_on = None

TABLES = ("analysis_snapshots", "population_source_aliases")


def upgrade() -> None:
    postgres = op.get_bind().dialect.name == "postgresql"
    if postgres:
        op.execute(
            "UPDATE analysis_snapshots SET created_at = "
            "COALESCE(NULLIF(payload_json->>'generated_at', '')::timestamptz, now()) WHERE created_at IS NULL"
        )
    else:
        op.execute(
            "UPDATE analysis_snapshots SET created_at = "
            "COALESCE(json_extract(payload_json, '$.generated_at'), CURRENT_TIMESTAMP) WHERE created_at IS NULL"
        )
    op.execute("UPDATE analysis_snapshots SET updated_at = created_at WHERE updated_at IS NULL")
    op.execute("UPDATE population_source_aliases SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL")
    op.execute("UPDATE population_source_aliases SET updated_at = created_at WHERE updated_at IS NULL")
    if not postgres:
        return
    for table in TABLES:
        for column in ("created_at", "updated_at"):
            op.alter_column(
                table,
                column,
                existing_type=sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table in TABLES:
        for column in ("created_at", "updated_at"):
            op.alter_column(
                table,
                column,
                existing_type=sa.DateTime(timezone=True),
                server_default=None,
                nullable=True,
            )

"""Remember which stored calculation runs are verified at the current analytics revision.

Revision ID: 0016_calculation_run_memos
Revises: 0015_sync_coverage_manifest
"""

import sqlalchemy as sa
from alembic import op

revision = "0016_calculation_run_memos"
down_revision = "0015_sync_coverage_manifest"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "calculation_run_memos",
        sa.Column("request_key", sa.String(64), primary_key=True),
        sa.Column(
            "calculation_run_id",
            sa.Uuid(),
            sa.ForeignKey("calculation_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("quality_scanned_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_calculation_run_memos_calculation_run_id", "calculation_run_memos", ["calculation_run_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_calculation_run_memos_calculation_run_id", table_name="calculation_run_memos")
    op.drop_table("calculation_run_memos")

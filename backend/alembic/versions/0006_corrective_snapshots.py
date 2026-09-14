"""Analytical snapshots, event programme binding, and exact-run columns.

Revision ID: 0006_corrective_snapshots
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_corrective_snapshots"
down_revision = "0005_phase567_ai_publishing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analysis_snapshots",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("org_unit_id", sa.Uuid(), sa.ForeignKey("org_units.id"), nullable=False),
        sa.Column("period", sa.String(40), nullable=False),
        sa.Column("comparison_period", sa.String(40)),
        sa.Column("module", sa.String(40), nullable=False),
        sa.Column("selected_indicator", sa.String(80)),
        sa.Column("view_hash", sa.String(64), nullable=False),
        sa.Column("current_run_id", sa.Uuid(), sa.ForeignKey("calculation_runs.id")),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("software_version", sa.String(40)),
        sa.Column("payload_json", sa.JSON()),
        sa.Column("evidence_json", sa.JSON()),
        sa.Column("view_config", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_analysis_snapshots_user_id", "analysis_snapshots", ["user_id"])
    op.create_index("ix_analysis_snapshots_view_hash", "analysis_snapshots", ["view_hash"])
    with op.batch_alter_table("raw_event_snapshots") as batch:
        batch.add_column(sa.Column("programme_id", sa.Uuid(), sa.ForeignKey("programmes.id")))
    with op.batch_alter_table("export_jobs") as batch:
        batch.add_column(sa.Column("analysis_snapshot_id", sa.Uuid(), sa.ForeignKey("analysis_snapshots.id")))
        batch.add_column(sa.Column("view_hash", sa.String(64)))
        batch.add_column(sa.Column("checksum", sa.String(128)))
        batch.add_column(sa.Column("idempotency_key", sa.String(80)))
    with op.batch_alter_table("ai_requests") as batch:
        batch.add_column(sa.Column("analysis_snapshot_id", sa.Uuid(), sa.ForeignKey("analysis_snapshots.id")))
    op.create_index(
        "ix_login_attempts_username_created",
        "login_attempts",
        ["username", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_login_attempts_username_created", table_name="login_attempts")
    with op.batch_alter_table("ai_requests") as batch:
        batch.drop_column("analysis_snapshot_id")
    with op.batch_alter_table("export_jobs") as batch:
        batch.drop_column("idempotency_key")
        batch.drop_column("checksum")
        batch.drop_column("view_hash")
        batch.drop_column("analysis_snapshot_id")
    with op.batch_alter_table("raw_event_snapshots") as batch:
        batch.drop_column("programme_id")
    op.drop_index("ix_analysis_snapshots_view_hash", table_name="analysis_snapshots")
    op.drop_index("ix_analysis_snapshots_user_id", table_name="analysis_snapshots")
    op.drop_table("analysis_snapshots")

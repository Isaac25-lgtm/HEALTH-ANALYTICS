"""Amendment corrections: idempotent analytical execution, explicit period rules,
population source identity and crosswalk, sync event windows, value reason codes.

Revision ID: 0007_amendment_corrections
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007_amendment_corrections"
down_revision = "0006_corrective_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("analysis_snapshots") as batch:
        batch.add_column(sa.Column("idempotency_key", sa.String(80)))
    op.create_index(
        "uq_analysis_snapshots_user_request",
        "analysis_snapshots",
        ["user_id", "idempotency_key"],
        unique=True,
        sqlite_where=sa.text("idempotency_key IS NOT NULL"),
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    # Existing rows are the financial-year convention recorded as binding decision D-004.
    # They govern FY periods only; a NULL period-kind list is read as ["fy"].
    with op.batch_alter_table("period_population_rules") as batch:
        batch.add_column(
            sa.Column("scope_kind", sa.String(20), nullable=False, server_default="financial_year")
        )
        batch.add_column(sa.Column("applies_to_period_kinds", sa.JSON()))
        batch.add_column(sa.Column("approval_status", sa.String(40), nullable=False, server_default="approved"))

    with op.batch_alter_table("sync_jobs") as batch:
        batch.add_column(sa.Column("window_start", sa.Date()))
        batch.add_column(sa.Column("window_end", sa.Date()))

    with op.batch_alter_table("population_versions") as batch:
        batch.add_column(sa.Column("source_dataset", sa.String(120)))
        batch.add_column(sa.Column("source_file_name", sa.String(255)))
        batch.add_column(sa.Column("source_sha256", sa.String(64)))
        batch.add_column(sa.Column("source_sheet", sa.String(120)))

    with op.batch_alter_table("population_values") as batch:
        batch.add_column(sa.Column("source_unit_name", sa.String(255)))
        batch.add_column(sa.Column("source_unit_type", sa.String(40)))
        batch.add_column(sa.Column("source_region", sa.String(80)))
        batch.add_column(sa.Column("source_column_label", sa.String(80)))

    with op.batch_alter_table("calculated_values") as batch:
        batch.add_column(sa.Column("reason_code", sa.String(80)))
        batch.add_column(sa.Column("event_snapshot_ids", sa.JSON()))
        batch.add_column(sa.Column("event_coverage", sa.JSON()))

    op.create_table(
        "population_source_aliases",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source_dataset", sa.String(120), nullable=False),
        sa.Column("source_unit_name", sa.String(255), nullable=False),
        sa.Column("source_unit_type", sa.String(40)),
        sa.Column("org_unit_id", sa.Uuid(), sa.ForeignKey("org_units.id")),
        sa.Column("target_name", sa.String(255)),
        sa.Column("decision_status", sa.String(20), nullable=False),
        sa.Column("decision_note", sa.Text()),
        sa.Column("proposed_by_user_id", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("decided_by_user_id", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("evidence", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("source_dataset", "source_unit_name"),
    )


def downgrade() -> None:
    op.drop_table("population_source_aliases")
    with op.batch_alter_table("calculated_values") as batch:
        batch.drop_column("event_coverage")
        batch.drop_column("event_snapshot_ids")
        batch.drop_column("reason_code")
    with op.batch_alter_table("population_values") as batch:
        batch.drop_column("source_column_label")
        batch.drop_column("source_region")
        batch.drop_column("source_unit_type")
        batch.drop_column("source_unit_name")
    with op.batch_alter_table("population_versions") as batch:
        batch.drop_column("source_sheet")
        batch.drop_column("source_sha256")
        batch.drop_column("source_file_name")
        batch.drop_column("source_dataset")
    with op.batch_alter_table("sync_jobs") as batch:
        batch.drop_column("window_end")
        batch.drop_column("window_start")
    with op.batch_alter_table("period_population_rules") as batch:
        batch.drop_column("approval_status")
        batch.drop_column("applies_to_period_kinds")
        batch.drop_column("scope_kind")
    op.drop_index("uq_analysis_snapshots_user_request", table_name="analysis_snapshots")
    with op.batch_alter_table("analysis_snapshots") as batch:
        batch.drop_column("idempotency_key")

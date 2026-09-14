"""Governed population import staging.

Preserves every row of an approved population source, with its match state, before any
organisation-unit crosswalk is approved. Staged rows are not denominators: they become draft
population values only through the existing apply and approval path.

Revision ID: 0011_population_import_staging
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011_population_import_staging"
down_revision = "0010_denominator_provenance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "population_import_batches",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source_dataset", sa.String(120), nullable=False),
        sa.Column("source_file_name", sa.String(255), nullable=False),
        sa.Column("source_display_name", sa.String(255)),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("source_type", sa.String(60), nullable=False),
        sa.Column("source_sheet", sa.String(120)),
        sa.Column("importer_version", sa.String(40), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("imported_by_user_id", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("year_min", sa.Integer()),
        sa.Column("year_max", sa.Integer()),
        sa.Column("unit_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("district_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("city_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("national_totals", sa.JSON()),
        sa.Column("region_totals", sa.JSON()),
        sa.Column("match_counts", sa.JSON()),
        sa.Column("reference_scope", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("review_status", sa.String(20), nullable=False),
        sa.Column("reviewed_by_user_id", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_population_import_batches_source_dataset", "population_import_batches", ["source_dataset"])

    op.create_table(
        "population_import_rows",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("batch_id", sa.Uuid(), sa.ForeignKey("population_import_batches.id"), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("source_unit_name", sa.String(255), nullable=False),
        sa.Column("source_unit_type", sa.String(40), nullable=False),
        sa.Column("source_region", sa.String(80)),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("population", sa.Integer(), nullable=False),
        sa.Column("source_column_label", sa.String(80)),
        sa.Column("match_state", sa.String(30), nullable=False),
        sa.Column("candidate_org_unit_id", sa.Uuid(), sa.ForeignKey("org_units.id")),
        sa.Column("alias_id", sa.Uuid(), sa.ForeignKey("population_source_aliases.id")),
        sa.Column("review_state", sa.String(20), nullable=False),
        sa.Column("validation_error", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("batch_id", "row_number", "year", name="uq_population_import_rows_cell"),
    )
    op.create_index("ix_population_import_rows_batch_id", "population_import_rows", ["batch_id"])
    op.create_index("ix_population_import_rows_match_state", "population_import_rows", ["match_state"])


def downgrade() -> None:
    op.drop_index("ix_population_import_rows_match_state", table_name="population_import_rows")
    op.drop_index("ix_population_import_rows_batch_id", table_name="population_import_rows")
    op.drop_table("population_import_rows")
    op.drop_index("ix_population_import_batches_source_dataset", table_name="population_import_batches")
    op.drop_table("population_import_batches")

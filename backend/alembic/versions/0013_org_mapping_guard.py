"""Prevent overlapping effective DHIS2 organisation-unit mappings on PostgreSQL.

Application validation gives friendly errors on every supported database. PostgreSQL receives
the final concurrency guard so two transactions cannot approve overlapping intervals together.

Revision ID: 0013_org_mapping_guard
"""

from __future__ import annotations

from alembic import op

revision = "0013_org_mapping_guard"
down_revision = "0012_population_staging_identity"
branch_labels = None
depends_on = None

CONSTRAINT = "ex_org_mapping_no_overlap"


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.execute(
        f"""
        ALTER TABLE org_unit_mappings
        ADD CONSTRAINT {CONSTRAINT}
        EXCLUDE USING gist (
            source_system WITH =,
            external_uid WITH =,
            daterange(
                COALESCE(valid_from, '-infinity'::date),
                COALESCE(valid_to, 'infinity'::date),
                '[]'
            ) WITH &&
        )
        """
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    # Alembic's drop_constraint only understands check/foreignkey/primary/unique, so an exclusion
    # constraint is dropped with explicit SQL, symmetrically with the raw DDL used to create it.
    op.execute(f"ALTER TABLE org_unit_mappings DROP CONSTRAINT IF EXISTS {CONSTRAINT}")

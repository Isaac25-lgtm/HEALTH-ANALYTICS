"""Persist how each population-derived denominator was resolved.

Records the period kind, parent financial year, population year, period fraction, coefficient,
annual and adjusted target and the population source on the calculated value itself, so a
published number stays explainable without recomputing anything.

Revision ID: 0010_denominator_provenance
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010_denominator_provenance"
down_revision = "0009_retention_and_artifact_storage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("calculated_values") as batch:
        batch.add_column(sa.Column("denominator_provenance", sa.JSON()))


def downgrade() -> None:
    with op.batch_alter_table("calculated_values") as batch:
        batch.drop_column("denominator_provenance")

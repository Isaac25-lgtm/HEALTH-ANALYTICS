"""Index calculation runs by input fingerprint so identical-input runs can be reused.

A dashboard calculation stores the SHA-256 fingerprint of its complete inputs in
``calculation_runs.idempotency_key``; later requests with identical inputs look it up.

Revision ID: 0014_calculation_run_reuse
"""

from __future__ import annotations

from alembic import op

revision = "0014_calculation_run_reuse"
down_revision = "0013_org_mapping_guard"
branch_labels = None
depends_on = None

INDEX = "ix_calculation_runs_idempotency_key"


def upgrade() -> None:
    op.create_index(INDEX, "calculation_runs", ["idempotency_key"])


def downgrade() -> None:
    op.drop_index(INDEX, table_name="calculation_runs")

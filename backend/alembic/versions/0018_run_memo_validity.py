"""Let a verified run carry the moment after which the clock alone would change it.

Revision ID: 0018_run_memo_validity
Revises: 0017_statement_revision_triggers
"""

import sqlalchemy as sa
from alembic import op

revision = "0018_run_memo_validity"
down_revision = "0017_statement_revision_triggers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("calculation_run_memos", sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("calculation_run_memos", "valid_until")

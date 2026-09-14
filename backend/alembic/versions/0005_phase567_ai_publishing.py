"""AI request metadata and export artifact columns.

Revision ID: 0005_phase567_ai_publishing
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_phase567_ai_publishing"
down_revision = "0004_phase12_audit_fixes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("export_jobs", sa.Column("file_path", sa.String(500)))
    op.add_column("export_jobs", sa.Column("module", sa.String(40)))
    op.add_column("export_jobs", sa.Column("comparison_period", sa.String(40)))
    op.add_column("export_jobs", sa.Column("metadata_json", sa.JSON()))
    op.add_column("ai_requests", sa.Column("prompt_version", sa.String(40)))
    op.add_column(
        "ai_requests",
        sa.Column("fallback_used", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("ai_requests", sa.Column("error_code", sa.String(80)))
    op.add_column("ai_requests", sa.Column("response_json", sa.JSON()))


def downgrade() -> None:
    op.drop_column("ai_requests", "response_json")
    op.drop_column("ai_requests", "error_code")
    op.drop_column("ai_requests", "fallback_used")
    op.drop_column("ai_requests", "prompt_version")
    op.drop_column("export_jobs", "metadata_json")
    op.drop_column("export_jobs", "comparison_period")
    op.drop_column("export_jobs", "module")
    op.drop_column("export_jobs", "file_path")

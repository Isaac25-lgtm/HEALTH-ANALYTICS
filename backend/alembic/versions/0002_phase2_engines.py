"""Explicit Phase 2 connector/quality/sync tables.

Revision ID: 0002_phase2_engines
"""

from __future__ import annotations

import sys
from pathlib import Path

revision = "0002_phase2_engines"
down_revision = "0001_phase1_foundation"
branch_labels = None
depends_on = None

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from historical.phase2 import downgrade_phase2, upgrade_phase2  # noqa: E402


def upgrade() -> None:
    upgrade_phase2()


def downgrade() -> None:
    downgrade_phase2()

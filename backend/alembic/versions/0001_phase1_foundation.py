"""Explicit Phase 1 foundation tables.

Revision ID: 0001_phase1_foundation
"""

from __future__ import annotations

import sys
from pathlib import Path

revision = "0001_phase1_foundation"
down_revision = None
branch_labels = None
depends_on = None

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from historical.phase1 import downgrade_phase1, upgrade_phase1  # noqa: E402


def upgrade() -> None:
    upgrade_phase1()


def downgrade() -> None:
    downgrade_phase1()

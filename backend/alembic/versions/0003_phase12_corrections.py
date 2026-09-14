"""Corrective constraints, sessions, provenance, and quality lifecycle.

Revision ID: 0003_phase12_corrections
"""

from __future__ import annotations

import sys
from pathlib import Path

revision = "0003_phase12_corrections"
down_revision = "0002_phase2_engines"
branch_labels = None
depends_on = None

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from historical.phase12_corrections import downgrade_corrections, upgrade_corrections  # noqa: E402


def upgrade() -> None:
    upgrade_corrections()


def downgrade() -> None:
    downgrade_corrections()

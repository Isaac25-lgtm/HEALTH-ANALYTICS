"""Programme-scoped raw aggregate lineage.

Revision ID: 0004_phase12_audit_fixes
"""

from __future__ import annotations

import sys
from pathlib import Path

revision = "0004_phase12_audit_fixes"
down_revision = "0003_phase12_corrections"
branch_labels = None
depends_on = None

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from historical.phase12_audit_fixes import downgrade_audit_fixes, upgrade_audit_fixes  # noqa: E402


def upgrade() -> None:
    upgrade_audit_fixes()


def downgrade() -> None:
    downgrade_audit_fixes()

"""Governed identity for population staging batches.

Adds the reference fingerprint (organisation-unit hierarchy, approved aliases and hierarchy
approval reference) and a unique identity of source checksum, importer version and fingerprint,
so re-staging the same source against the same reference reuses one batch instead of creating
unlimited duplicates. Existing batches keep a NULL fingerprint and are not merged.

Revision ID: 0012_population_staging_identity
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012_population_staging_identity"
down_revision = "0011_population_import_staging"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("population_import_batches") as batch:
        batch.add_column(sa.Column("reference_fingerprint", sa.String(64)))
    op.create_index(
        "uq_population_import_batches_identity",
        "population_import_batches",
        ["source_sha256", "importer_version", "reference_fingerprint"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_population_import_batches_identity", table_name="population_import_batches")
    with op.batch_alter_table("population_import_batches") as batch:
        batch.drop_column("reference_fingerprint")

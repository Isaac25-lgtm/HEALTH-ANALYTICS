"""Export queue durability: one live job per user + snapshot + export type, bounded
attempts, dispatch and claim state, and a widened idempotency key.

The 0006 key column was VARCHAR(80), but ``<user uuid>:<snapshot uuid>:powerpoint`` is 84
characters, so PowerPoint exports could not be stored on PostgreSQL.

Revision ID: 0008_export_queue_durability
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008_export_queue_durability"
down_revision = "0007_amendment_corrections"
branch_labels = None
depends_on = None

LIVE_STATUSES = ("queued", "running", "succeeded")


def upgrade() -> None:
    with op.batch_alter_table("export_jobs") as batch:
        batch.alter_column("idempotency_key", existing_type=sa.String(80), type_=sa.String(200))
        batch.add_column(sa.Column("active_key", sa.String(200)))
        batch.add_column(sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("max_attempts", sa.Integer()))
        batch.add_column(sa.Column("dispatch_state", sa.String(20)))
        batch.add_column(sa.Column("celery_task_id", sa.String(155)))
        batch.add_column(sa.Column("claim_token", sa.String(64)))
        batch.add_column(sa.Column("claimed_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("dispatched_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("started_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("finished_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("last_error_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("retry_scheduled", sa.Boolean(), nullable=False, server_default=sa.false()))

    jobs = sa.table(
        "export_jobs",
        sa.column("id", sa.Uuid()),
        sa.column("status", sa.String()),
        sa.column("idempotency_key", sa.String()),
        sa.column("active_key", sa.String()),
        sa.column("attempt_count", sa.Integer()),
        sa.column("dispatch_state", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    bind = op.get_bind()
    rows = bind.execute(sa.select(jobs.c.id, jobs.c.status, jobs.c.idempotency_key, jobs.c.created_at)).all()
    # Jobs created before this revision were never dispatched to a worker by the API. They are
    # marked "legacy" so nobody mistakes an old queued row for a dispatched one.
    for row in rows:
        attempts = 1 if row.status in {"running", "succeeded", "failed"} else 0
        bind.execute(
            jobs.update().where(jobs.c.id == row.id).values(dispatch_state="legacy", attempt_count=attempts)
        )
    newest: dict[str, tuple] = {}
    for row in rows:
        if not row.idempotency_key or row.status not in LIVE_STATUSES:
            continue
        rank = (row.created_at is not None, row.created_at, str(row.id))
        current = newest.get(row.idempotency_key)
        if current is None or rank > current[0]:
            newest[row.idempotency_key] = (rank, row.id)
    # Older duplicates keep their status, artifact and history; only the newest live row
    # becomes the idempotent job for its key.
    for key, (_rank, job_id) in newest.items():
        bind.execute(jobs.update().where(jobs.c.id == job_id).values(active_key=key))
    op.create_index("uq_export_jobs_active_key", "export_jobs", ["active_key"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_export_jobs_active_key", table_name="export_jobs")
    # 0007 stored keys as VARCHAR(80). Longer keys cannot be represented there; the key is
    # not a uniqueness constraint at 0007, so it is cleared rather than truncated.
    op.get_bind().execute(sa.text("UPDATE export_jobs SET idempotency_key = NULL WHERE length(idempotency_key) > 80"))
    with op.batch_alter_table("export_jobs") as batch:
        batch.drop_column("retry_scheduled")
        batch.drop_column("last_error_at")
        batch.drop_column("finished_at")
        batch.drop_column("started_at")
        batch.drop_column("dispatched_at")
        batch.drop_column("claimed_at")
        batch.drop_column("claim_token")
        batch.drop_column("celery_task_id")
        batch.drop_column("dispatch_state")
        batch.drop_column("max_attempts")
        batch.drop_column("attempt_count")
        batch.drop_column("active_key")
        batch.alter_column("idempotency_key", existing_type=sa.String(200), type_=sa.String(80))

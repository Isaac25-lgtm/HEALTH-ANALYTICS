"""Retention and Render-safe export artifacts.

Adds the maintenance/purge audit tables, the provider-neutral maintenance lease, database-backed
export artifact storage for deployments without a shared filesystem, artifact expiry metadata on
export jobs, and the indexes the retention scans need.

Backfill is deterministic: existing succeeded jobs that still name a file are marked as
filesystem-stored and expire 24 hours (the approved default window) after they finished.

Revision ID: 0009_retention_and_artifact_storage
"""

from __future__ import annotations

from datetime import datetime, timedelta

import sqlalchemy as sa
from alembic import op

revision = "0009_retention_and_artifact_storage"
down_revision = "0008_export_queue_durability"
branch_labels = None
depends_on = None

DEFAULT_EXPORT_FILE_RETENTION_HOURS = 24


def upgrade() -> None:
    with op.batch_alter_table("export_jobs") as batch:
        batch.add_column(sa.Column("artifact_storage", sa.String(20)))
        batch.add_column(sa.Column("artifact_media_type", sa.String(120)))
        batch.add_column(sa.Column("artifact_size_bytes", sa.Integer()))
        batch.add_column(sa.Column("artifact_expires_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("artifact_deleted_at", sa.DateTime(timezone=True)))

    op.create_table(
        "export_artifacts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("export_job_id", sa.Uuid(), sa.ForeignKey("export_jobs.id"), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("media_type", sa.String(120)),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("checksum", sa.String(128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("export_job_id", name="uq_export_artifacts_job"),
    )
    op.create_index("ix_export_artifacts_expires_at", "export_artifacts", ["expires_at"])

    op.create_table(
        "maintenance_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("task_type", sa.String(40), nullable=False),
        sa.Column("policy", sa.String(40), nullable=False),
        sa.Column("entity", sa.String(60), nullable=False),
        sa.Column("requested_cutoff", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("rows_examined", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_deleted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("files_examined", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("files_deleted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("batches", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("error_code", sa.String(80)),
        sa.Column("error_summary", sa.String(500)),
        sa.Column("software_version", sa.String(40)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_maintenance_runs_task_type", "maintenance_runs", ["task_type"])
    op.create_index("ix_maintenance_runs_started_at", "maintenance_runs", ["started_at"])

    op.create_table(
        "maintenance_locks",
        sa.Column("name", sa.String(80), primary_key=True),
        sa.Column("holder", sa.String(64), nullable=False),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )

    # Retention scans are range queries over these timestamps.
    op.create_index("ix_raw_aggregate_values_extracted_at", "raw_aggregate_values", ["extracted_at"])
    op.create_index("ix_raw_event_snapshots_extracted_at", "raw_event_snapshots", ["extracted_at"])
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"])
    op.create_index("ix_analysis_snapshots_created_at", "analysis_snapshots", ["created_at"])
    op.create_index("ix_calculation_runs_created_at", "calculation_runs", ["created_at"])
    op.create_index("ix_export_jobs_finished_at", "export_jobs", ["finished_at"])
    op.create_index("ix_export_jobs_artifact_expires_at", "export_jobs", ["artifact_expires_at"])

    jobs = sa.table(
        "export_jobs",
        sa.column("id", sa.Uuid()),
        sa.column("status", sa.String()),
        sa.column("file_path", sa.String()),
        sa.column("finished_at", sa.DateTime(timezone=True)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("artifact_storage", sa.String()),
        sa.column("artifact_expires_at", sa.DateTime(timezone=True)),
    )
    bind = op.get_bind()
    rows = bind.execute(
        sa.select(jobs.c.id, jobs.c.finished_at, jobs.c.created_at).where(
            jobs.c.status == "succeeded", jobs.c.file_path.is_not(None)
        )
    ).all()
    for row in rows:
        published = row.finished_at or row.created_at
        bind.execute(
            jobs.update()
            .where(jobs.c.id == row.id)
            .values(artifact_storage="filesystem", artifact_expires_at=_expiry(published))
        )


def _expiry(published: datetime | None) -> datetime | None:
    if published is None:
        return None
    return published + timedelta(hours=DEFAULT_EXPORT_FILE_RETENTION_HOURS)


def downgrade() -> None:
    op.drop_index("ix_export_jobs_artifact_expires_at", table_name="export_jobs")
    op.drop_index("ix_export_jobs_finished_at", table_name="export_jobs")
    op.drop_index("ix_calculation_runs_created_at", table_name="calculation_runs")
    op.drop_index("ix_analysis_snapshots_created_at", table_name="analysis_snapshots")
    op.drop_index("ix_audit_log_created_at", table_name="audit_log")
    op.drop_index("ix_raw_event_snapshots_extracted_at", table_name="raw_event_snapshots")
    op.drop_index("ix_raw_aggregate_values_extracted_at", table_name="raw_aggregate_values")
    op.drop_table("maintenance_locks")
    op.drop_index("ix_maintenance_runs_started_at", table_name="maintenance_runs")
    op.drop_index("ix_maintenance_runs_task_type", table_name="maintenance_runs")
    op.drop_table("maintenance_runs")
    op.drop_index("ix_export_artifacts_expires_at", table_name="export_artifacts")
    op.drop_table("export_artifacts")
    with op.batch_alter_table("export_jobs") as batch:
        batch.drop_column("artifact_deleted_at")
        batch.drop_column("artifact_expires_at")
        batch.drop_column("artifact_size_bytes")
        batch.drop_column("artifact_media_type")
        batch.drop_column("artifact_storage")

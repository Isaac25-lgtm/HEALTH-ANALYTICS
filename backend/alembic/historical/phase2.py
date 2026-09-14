"""Frozen Phase 2 delta. Do not import application ORM models."""

import sqlalchemy as sa
from alembic import op

PHASE2_TABLES = [
    "source_mappings",
    "event_field_mappings",
    "sync_jobs",
    "quality_rules",
    "freshness_snapshots",
    "operational_events",
]


def _now_col(name: str) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        server_default=sa.text("CURRENT_TIMESTAMP"),
        nullable=False,
    )


def _ts() -> list:
    return [_now_col("created_at"), _now_col("updated_at")]


def upgrade_phase2() -> None:
    op.create_table(
        "source_mappings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("internal_source_key", sa.String(120), nullable=False),
        sa.Column("programme_id", sa.Uuid(), sa.ForeignKey("programmes.id"), nullable=False),
        sa.Column("dhis2_item_uid", sa.String(80)),
        sa.Column("item_kind", sa.String(40), nullable=False, server_default="data_element"),
        sa.Column("category_option_combo_uid", sa.String(80)),
        sa.Column("aggregation_semantics", sa.String(80)),
        sa.Column("mapping_version", sa.String(40), nullable=False, server_default="v1"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("notes", sa.Text()),
        sa.Column("valid_from", sa.Date()),
        sa.Column("valid_to", sa.Date()),
        *_ts(),
        sa.UniqueConstraint("internal_source_key", "mapping_version", "programme_id"),
    )
    op.create_index("ix_source_mappings_internal_source_key", "source_mappings", ["internal_source_key"])
    op.create_table(
        "event_field_mappings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("programme_id", sa.Uuid(), sa.ForeignKey("programmes.id")),
        sa.Column("program_uid", sa.String(80)),
        sa.Column("program_stage_uid", sa.String(80)),
        sa.Column("source_data_element_uid", sa.String(80)),
        sa.Column("internal_semantic_field", sa.String(120), nullable=False),
        sa.Column("expected_data_type", sa.String(40), nullable=False, server_default="string"),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("mapping_version", sa.String(40), nullable=False, server_default="v1"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("notes", sa.Text()),
        sa.Column("valid_from", sa.Date()),
        sa.Column("valid_to", sa.Date()),
        *_ts(),
        sa.UniqueConstraint("internal_semantic_field", "mapping_version", "event_type"),
    )
    op.create_table(
        "sync_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("job_type", sa.String(40), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="queued"),
        sa.Column("org_unit_id", sa.Uuid(), sa.ForeignKey("org_units.id")),
        sa.Column("programme_id", sa.Uuid(), sa.ForeignKey("programmes.id")),
        sa.Column("period_from", sa.String(40)),
        sa.Column("period_to", sa.String(40)),
        sa.Column("mapping_version", sa.String(40)),
        sa.Column("requested_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("received_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stored_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rejected_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("flagged_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("error_code", sa.String(80)),
        sa.Column("error_message", sa.Text()),
        sa.Column("source_freshness_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("initiated_by_user_id", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("cancelled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("notes", sa.Text()),
        *_ts(),
    )
    op.create_index("ix_sync_jobs_job_type", "sync_jobs", ["job_type"])
    op.create_table(
        "quality_rules",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("rule_version", sa.String(40), nullable=False, server_default="v1"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("config", sa.JSON()),
        *_ts(),
        sa.UniqueConstraint("code", "rule_version"),
    )
    op.create_table(
        "freshness_snapshots",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("connector", sa.String(40), nullable=False),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("source_freshness_at", sa.DateTime(timezone=True)),
        sa.Column("lag_seconds", sa.Integer()),
        sa.Column("status", sa.String(40), nullable=False, server_default="unknown"),
        sa.Column("sync_job_id", sa.Uuid(), sa.ForeignKey("sync_jobs.id")),
        sa.Column("detail", sa.JSON()),
        *_ts(),
    )
    op.create_index("ix_freshness_snapshots_connector", "freshness_snapshots", ["connector"])
    op.create_table(
        "operational_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("job_id", sa.String(80)),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("retry_count", sa.Integer()),
        sa.Column("records_received", sa.Integer()),
        sa.Column("records_stored", sa.Integer()),
        sa.Column("records_rejected", sa.Integer()),
        sa.Column("payload", sa.JSON()),
        _now_col("created_at"),
    )
    op.create_index("ix_operational_events_event_type", "operational_events", ["event_type"])
    _add_fk_column("raw_aggregate_values", "sync_job_id", "sync_jobs")
    _add_fk_column("raw_event_snapshots", "sync_job_id", "sync_jobs")
    _add_fk_column("calculation_runs", "sync_job_id", "sync_jobs")
    _add_fk_column("data_quality_flags", "sync_job_id", "sync_jobs")


def _add_fk_column(table: str, column: str, referred: str) -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column(column, sa.Uuid()))
            batch.create_foreign_key(f"fk_{table}_{column}_{referred}", referred, [column], ["id"])
    else:
        op.add_column(table, sa.Column(column, sa.Uuid(), sa.ForeignKey(f"{referred}.id")))


def _drop_columns(table: str, columns: list[str]) -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(table) as batch:
            for column in columns:
                batch.drop_column(column)
    else:
        for column in columns:
            op.drop_column(table, column)


def downgrade_phase2() -> None:
    _drop_columns("data_quality_flags", ["sync_job_id"])
    _drop_columns("calculation_runs", ["sync_job_id"])
    _drop_columns("raw_event_snapshots", ["sync_job_id"])
    _drop_columns("raw_aggregate_values", ["sync_job_id"])
    for name in reversed(PHASE2_TABLES):
        op.drop_table(name)

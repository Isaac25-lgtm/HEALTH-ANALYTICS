"""Corrective Phase 1/2 schema. Do not import application ORM models."""

import sqlalchemy as sa
from alembic import op


def _sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def _add_columns(table: str, columns: list[sa.Column], fks: list[tuple[str, str, str]] | None = None) -> None:
    if _sqlite():
        with op.batch_alter_table(table) as batch:
            for column in columns:
                batch.add_column(column)
            for name, referred, col in fks or []:
                batch.create_foreign_key(name, referred, [col], ["id"])
    else:
        for column in columns:
            op.add_column(table, column)
        for name, referred, col in fks or []:
            op.create_foreign_key(name, table, referred, [col], ["id"])


def upgrade_corrections() -> None:
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("jti", sa.String(64), nullable=False),
        sa.Column("csrf_token", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("ip_address", sa.String(80)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.UniqueConstraint("jti"),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_table(
        "login_attempts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("username", sa.String(80), nullable=False),
        sa.Column("succeeded", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("ip_address", sa.String(80)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )
    op.create_index("ix_login_attempts_username", "login_attempts", ["username"])

    _add_columns(
        "user_geography_scopes",
        [
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("valid_from", sa.Date()),
            sa.Column("valid_to", sa.Date()),
        ],
    )
    _add_columns(
        "user_programme_scopes",
        [
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("valid_from", sa.Date()),
            sa.Column("valid_to", sa.Date()),
        ],
    )
    _add_columns(
        "facility_population_entries",
        [
            sa.Column("is_current_approved", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("approved_at", sa.DateTime(timezone=True)),
            sa.Column("rejected_at", sa.DateTime(timezone=True)),
            sa.Column("rejected_by_user_id", sa.Uuid()),
            sa.Column("rejection_reason", sa.Text()),
        ],
        fks=[("fk_facility_rejected_by_users", "users", "rejected_by_user_id")],
    )
    op.create_index(
        "uq_facility_current_approved",
        "facility_population_entries",
        ["org_unit_id", "year"],
        unique=True,
        sqlite_where=sa.text("is_current_approved = 1"),
        postgresql_where=sa.text("is_current_approved"),
    )

    _add_columns(
        "raw_aggregate_values",
        [sa.Column("value_invalid", sa.Boolean(), nullable=False, server_default=sa.false())],
    )
    op.drop_index("uq_raw_aggregate_current", table_name="raw_aggregate_values")
    op.create_index(
        "uq_raw_aggregate_current",
        "raw_aggregate_values",
        ["source_system", "org_unit_id", "period", "internal_source_key", "category_option_combo_uid"],
        unique=True,
        sqlite_where=sa.text("is_current = 1"),
        postgresql_where=sa.text("is_current"),
    )

    _add_columns(
        "calculation_runs",
        [
            sa.Column("software_version", sa.String(40)),
            sa.Column("aggregation_policy", sa.String(80)),
            sa.Column("evidence_manifest", sa.JSON()),
            sa.Column("idempotency_key", sa.String(80)),
        ],
    )
    _add_columns(
        "calculated_values",
        [
            sa.Column("facility_population_entry_id", sa.Uuid()),
            sa.Column("aggregation_policy", sa.String(80)),
            sa.Column("aggregation_level", sa.String(40)),
            sa.Column("source_row_ids", sa.JSON()),
            sa.Column("source_mapping_ids", sa.JSON()),
            sa.Column("software_version", sa.String(40)),
            sa.Column("missing_components", sa.JSON()),
        ],
        fks=[("fk_calc_values_facility_entry", "facility_population_entries", "facility_population_entry_id")],
    )
    _add_columns(
        "data_quality_flags",
        [
            sa.Column("fingerprint", sa.String(128)),
            sa.Column("reopen_count", sa.Integer(), nullable=False, server_default="0"),
        ],
    )
    op.create_index("ix_dq_flags_fingerprint", "data_quality_flags", ["fingerprint"])
    op.create_index("ix_dq_flags_org_period", "data_quality_flags", ["org_unit_id", "period"])
    op.create_index(
        "uq_dq_flag_open_fingerprint",
        "data_quality_flags",
        ["fingerprint"],
        unique=True,
        sqlite_where=sa.text("status IN ('open', 'acknowledged')"),
        postgresql_where=sa.text("status IN ('open', 'acknowledged')"),
    )

    _add_columns(
        "sync_jobs",
        [
            sa.Column("idempotency_key", sa.String(80)),
            sa.Column("page_limit_reached", sa.Boolean(), nullable=False, server_default=sa.false()),
        ],
    )

    op.create_index(
        "uq_indicator_versions_current",
        "indicator_versions",
        ["indicator_id"],
        unique=True,
        sqlite_where=sa.text("is_current = 1"),
        postgresql_where=sa.text("is_current"),
    )


def _drop_columns(table: str, columns: list[str]) -> None:
    if _sqlite():
        with op.batch_alter_table(table) as batch:
            for column in columns:
                batch.drop_column(column)
    else:
        for column in columns:
            op.drop_column(table, column)


def downgrade_corrections() -> None:
    op.drop_index("uq_indicator_versions_current", table_name="indicator_versions")
    _drop_columns("sync_jobs", ["page_limit_reached", "idempotency_key"])
    op.drop_index("uq_dq_flag_open_fingerprint", table_name="data_quality_flags")
    op.drop_index("ix_dq_flags_org_period", table_name="data_quality_flags")
    op.drop_index("ix_dq_flags_fingerprint", table_name="data_quality_flags")
    _drop_columns("data_quality_flags", ["reopen_count", "fingerprint"])
    _drop_columns(
        "calculated_values",
        [
            "missing_components",
            "software_version",
            "source_mapping_ids",
            "source_row_ids",
            "aggregation_level",
            "aggregation_policy",
            "facility_population_entry_id",
        ],
    )
    _drop_columns(
        "calculation_runs",
        ["idempotency_key", "evidence_manifest", "aggregation_policy", "software_version"],
    )
    op.drop_index("uq_raw_aggregate_current", table_name="raw_aggregate_values")
    op.create_index(
        "uq_raw_aggregate_current",
        "raw_aggregate_values",
        ["org_unit_id", "period", "internal_source_key"],
        unique=True,
        sqlite_where=sa.text("is_current = 1"),
        postgresql_where=sa.text("is_current"),
    )
    _drop_columns("raw_aggregate_values", ["value_invalid"])
    op.drop_index("uq_facility_current_approved", table_name="facility_population_entries")
    _drop_columns(
        "facility_population_entries",
        ["rejection_reason", "rejected_by_user_id", "rejected_at", "approved_at", "is_current_approved"],
    )
    _drop_columns("user_programme_scopes", ["valid_to", "valid_from", "is_active"])
    _drop_columns("user_geography_scopes", ["valid_to", "valid_from", "is_active"])
    op.drop_table("login_attempts")
    op.drop_table("auth_sessions")

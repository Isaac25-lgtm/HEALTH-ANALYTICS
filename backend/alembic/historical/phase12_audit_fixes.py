"""Post-audit Phase 1/2 schema fixes. Do not import application ORM models."""

import sqlalchemy as sa
from alembic import op


def _sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def _backfill_raw_programmes() -> None:
    """Backfill only from unambiguous historical mapping lineage; never guess a programme."""
    bind = op.get_bind()
    if _sqlite():
        op.execute(
            sa.text(
                """
                UPDATE raw_aggregate_values
                SET programme_id = (
                    SELECT sm.programme_id
                    FROM source_mappings AS sm
                    WHERE replace(sm.id, '-', '') = replace(
                        json_extract(raw_aggregate_values.provenance, '$.mapping_id'), '-', ''
                    )
                    LIMIT 1
                )
                WHERE programme_id IS NULL
                  AND json_extract(provenance, '$.mapping_id') IS NOT NULL
                """
            )
        )
    else:
        op.execute(
            sa.text(
                """
                UPDATE raw_aggregate_values AS raw
                SET programme_id = sm.programme_id
                FROM source_mappings AS sm
                WHERE raw.programme_id IS NULL
                  AND replace(sm.id::text, '-', '') = replace(raw.provenance->>'mapping_id', '-', '')
                """
            )
        )
    op.execute(
        sa.text(
            """
            UPDATE raw_aggregate_values AS raw
            SET programme_id = (
                SELECT sm.programme_id
                FROM source_mappings AS sm
                WHERE sm.internal_source_key = raw.internal_source_key
                  AND COALESCE(sm.dhis2_item_uid, '') = COALESCE(raw.dhis2_item_uid, '')
                  AND COALESCE(sm.category_option_combo_uid, '') =
                      COALESCE(raw.category_option_combo_uid, '')
                  AND COALESCE(sm.mapping_version, '') = COALESCE(raw.mapping_version, '')
                GROUP BY sm.programme_id
                LIMIT 1
            )
            WHERE raw.programme_id IS NULL
              AND 1 = (
                  SELECT COUNT(DISTINCT sm.programme_id)
                  FROM source_mappings AS sm
                  WHERE sm.internal_source_key = raw.internal_source_key
                    AND COALESCE(sm.dhis2_item_uid, '') = COALESCE(raw.dhis2_item_uid, '')
                    AND COALESCE(sm.category_option_combo_uid, '') =
                        COALESCE(raw.category_option_combo_uid, '')
                    AND COALESCE(sm.mapping_version, '') = COALESCE(raw.mapping_version, '')
              )
            """
        )
    )
    unresolved_dhis2 = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM raw_aggregate_values "
            "WHERE source_system = 'dhis2' AND programme_id IS NULL"
        )
    ).scalar_one()
    if unresolved_dhis2:
        raise RuntimeError(
            f"Cannot infer programme for {unresolved_dhis2} historical DHIS2 raw rows. "
            "Reconcile their source mapping lineage before applying revision 0004."
        )


def upgrade_audit_fixes() -> None:
    if _sqlite():
        with op.batch_alter_table("raw_aggregate_values") as batch:
            batch.add_column(sa.Column("programme_id", sa.Uuid()))
            batch.create_foreign_key(
                "fk_raw_aggregate_programme", "programmes", ["programme_id"], ["id"]
            )
    else:
        op.add_column("raw_aggregate_values", sa.Column("programme_id", sa.Uuid()))
        op.create_foreign_key(
            "fk_raw_aggregate_programme",
            "raw_aggregate_values",
            "programmes",
            ["programme_id"],
            ["id"],
        )
    _backfill_raw_programmes()
    op.create_index(
        "ix_raw_aggregate_values_programme_id",
        "raw_aggregate_values",
        ["programme_id"],
    )
    op.drop_index("uq_raw_aggregate_current", table_name="raw_aggregate_values")
    op.create_index(
        "uq_raw_aggregate_current",
        "raw_aggregate_values",
        [
            "source_system",
            "programme_id",
            "org_unit_id",
            "period",
            "internal_source_key",
            "category_option_combo_uid",
        ],
        unique=True,
        sqlite_where=sa.text("is_current = 1"),
        postgresql_where=sa.text("is_current"),
    )
    op.create_index(
        "uq_geometry_current",
        "geometries",
        ["org_unit_id"],
        unique=True,
        sqlite_where=sa.text("valid_to IS NULL"),
        postgresql_where=sa.text("valid_to IS NULL"),
    )


def downgrade_audit_fixes() -> None:
    op.drop_index("uq_geometry_current", table_name="geometries")
    op.drop_index("uq_raw_aggregate_current", table_name="raw_aggregate_values")
    op.create_index(
        "uq_raw_aggregate_current",
        "raw_aggregate_values",
        ["source_system", "org_unit_id", "period", "internal_source_key", "category_option_combo_uid"],
        unique=True,
        sqlite_where=sa.text("is_current = 1"),
        postgresql_where=sa.text("is_current"),
    )
    op.drop_index("ix_raw_aggregate_values_programme_id", table_name="raw_aggregate_values")
    if _sqlite():
        with op.batch_alter_table("raw_aggregate_values") as batch:
            batch.drop_column("programme_id")
    else:
        op.drop_constraint(
            "fk_raw_aggregate_programme", "raw_aggregate_values", type_="foreignkey"
        )
        op.drop_column("raw_aggregate_values", "programme_id")

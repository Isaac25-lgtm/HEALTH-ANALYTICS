"""Regression coverage for the isolated synthetic dashboard fixture."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.config import Settings
from app.models import OrgUnit, Programme, RawAggregateValue, SourceMapping, User
from app.services.demo_data import (
    KEY_RATE,
    SOURCE_SYSTEM,
    _catalogue_source_keys,
    _catalogue_sources,
    seed_demo_analytics,
)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def test_demo_seed_refuses_non_development_environments(session):
    settings = Settings(_env_file=None, app_env="production")

    with pytest.raises(RuntimeError, match="development and test only"):
        seed_demo_analytics(session, settings=settings)

    assert session.scalar(select(func.count()).select_from(RawAggregateValue)) == 0


def test_demo_seed_is_complete_deterministic_idempotent_and_source_isolated(session):
    assert set(KEY_RATE) == set(_catalogue_source_keys())
    expected_sources = set(_catalogue_sources())

    first = seed_demo_analytics(session)
    session.commit()

    programmes = {row.id: row.code for row in session.scalars(select(Programme)).all()}
    mappings = list(session.scalars(select(SourceMapping).where(SourceMapping.mapping_version == "demo")).all())
    assert {(row.internal_source_key, programmes[row.programme_id]) for row in mappings} == expected_sources
    assert all(row.dhis2_item_uid == f"DEMO_{row.internal_source_key}" for row in mappings)

    demo_rows = list(
        session.scalars(select(RawAggregateValue).where(RawAggregateValue.source_system == SOURCE_SYSTEM)).all()
    )
    assert first["raw_values"] == len(demo_rows)
    assert {(row.internal_source_key, programmes[row.programme_id]) for row in demo_rows} == expected_sources
    # One provenance timestamp for the whole fixture, recent enough that the demonstration data is
    # not reported as stale. A fixed calendar constant would age into 180 stale-reporting flags.
    seeded_at = {_as_utc(row.extracted_at) for row in demo_rows}
    assert len(seeded_at) == 1
    first_seeded_at = seeded_at.pop()
    assert (datetime.now(UTC) - first_seeded_at).total_seconds() < 3600
    assert all(row.dhis2_item_uid == f"DEMO_{row.internal_source_key}" for row in demo_rows)

    facility = session.scalar(select(OrgUnit).where(OrgUnit.code == "PADER_HC_III"))
    mnch = session.scalar(select(Programme).where(Programme.code == "MNCH"))
    protected = RawAggregateValue(
        source_system="dhis2",
        programme_id=mnch.id,
        org_unit_id=facility.id,
        period="FY2024/25",
        source_metric_id="TEST_UID_ANC1",
        internal_source_key="ANC1",
        dhis2_item_uid="TEST_UID_ANC1",
        value=999,
        extracted_at=datetime(2026, 8, 31, tzinfo=UTC),
        mapping_version="test",
        is_current=True,
        checksum="protected-non-demo-row",
    )
    session.add(protected)
    session.commit()
    original_count = len(demo_rows)

    second = seed_demo_analytics(session)
    session.commit()
    session.refresh(protected)

    assert float(protected.value) == 999
    assert protected.checksum == "protected-non-demo-row"
    assert second["raw_values"] == original_count
    assert (
        session.scalar(
            select(func.count()).select_from(RawAggregateValue).where(RawAggregateValue.source_system == SOURCE_SYSTEM)
        )
        == original_count
    )
    reseeded = list(
        session.scalars(select(RawAggregateValue).where(RawAggregateValue.source_system == SOURCE_SYSTEM)).all()
    )
    # Re-seeding never rewrites provenance: the fixture keeps its first seeding time.
    assert {_as_utc(row.extracted_at) for row in reseeded} == {first_seeded_at}


def test_demo_catalogue_values_resolve_in_epi_and_mpdsr(session):
    from app.services.modules import evaluate_module

    seed_demo_analytics(session)
    session.commit()
    uganda = session.scalar(select(OrgUnit).where(OrgUnit.code == "UG"))
    admin = session.scalar(select(User).where(User.username == "admin.user"))

    immunization = evaluate_module(
        session,
        user=admin,
        org_unit_id=uganda.id,
        period="FY2026/27",
        module="immunization",
        include_children=True,
    )
    epi_by_code = {row["indicator_code"]: row for row in immunization["indicators"]}
    assert epi_by_code["MR_COVERAGE"]["raw_value"] is not None
    assert epi_by_code["YF_COVERAGE"]["raw_value"] is not None
    assert epi_by_code["MR_COVERAGE"]["mapping_version"] == "demo"
    assert epi_by_code["YF_COVERAGE"]["mapping_version"] == "demo"

    mpdsr = evaluate_module(
        session,
        user=admin,
        org_unit_id=uganda.id,
        period="FY2026/27",
        module="mpdsr",
        include_children=True,
    )
    mpdsr_by_code = {row["indicator_code"]: row for row in mpdsr["indicators"]}
    assert mpdsr_by_code["MATERNAL_REPORTED_DEATHS"]["raw_value"] is not None
    assert mpdsr_by_code["MATERNAL_REPORTED_DEATHS"]["mapping_version"] == "demo"

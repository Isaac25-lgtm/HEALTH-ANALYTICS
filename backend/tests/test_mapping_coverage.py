"""A programme is only extractable when its formulas' source keys are all mapped."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.domain.enums import ConnectorType
from app.models import OrgUnit, OrgUnitMapping, Programme, SourceMapping
from app.services.mapping_coverage import (
    CoverageError,
    ensure_coverage,
    evaluate_coverage,
    required_source_keys,
)
from app.services.sync import enqueue_sync_job, execute_sync_job
from tests.test_dhis2_extraction_safety import _enabled_settings


def test_each_programme_declares_the_source_keys_its_formulas_need():
    mnch = required_source_keys("MNCH")
    epi = required_source_keys("EPI")
    mpdsr = required_source_keys("MPDSR")
    assert "ANC1" in mnch
    assert "BCG" in epi
    assert "MATERNAL_DEATHS" in mpdsr
    # The three programmes together define the platform's whole aggregate source surface.
    assert len(mnch | epi | mpdsr) == 48


def test_one_mapping_does_not_cover_a_programme(session):
    programme = session.scalar(select(Programme).where(Programme.code == "MNCH"))
    session.add(
        SourceMapping(
            internal_source_key="ANC1",
            programme_id=programme.id,
            dhis2_item_uid="TEST_UID_ANC1",
            mapping_version="v1",
            enabled=True,
        )
    )
    session.flush()

    report = evaluate_coverage(session, programme_id=programme.id, mapping_version="v1")
    assert "ANC1" in report.resolved
    assert report.unresolved, "the remaining MNCH keys are still unmapped"
    assert not report.complete

    with pytest.raises(CoverageError) as excinfo:
        ensure_coverage(session, programme_id=programme.id, mapping_version="v1")
    assert excinfo.value.code == "mapping_coverage_incomplete"
    assert excinfo.value.report.resolved == ["ANC1"]


def test_complete_coverage_passes_the_preflight(session):
    programme = session.scalar(select(Programme).where(Programme.code == "MNCH"))
    for index, key in enumerate(sorted(required_source_keys("MNCH"))):
        session.add(
            SourceMapping(
                internal_source_key=key,
                programme_id=programme.id,
                dhis2_item_uid=f"TEST_UID_{index}",
                mapping_version="v1",
                enabled=True,
            )
        )
    session.flush()

    report = ensure_coverage(session, programme_id=programme.id, mapping_version="v1")
    assert report.complete
    assert report.unresolved == []


def test_partial_coverage_cannot_report_a_programme_as_freshly_synchronised(session, monkeypatch):
    """One mapped key must not make a whole programme look up to date.

    The job itself is allowed to run: the first supervised validation is deliberately one metric,
    one organisation unit and one closed month. What must not happen is the programme's freshness
    reading as a complete success while most of its formulas remain unmapped.
    """
    settings = _enabled_settings()
    monkeypatch.setattr("app.services.sync.get_settings", lambda: settings)

    pader = session.scalar(select(OrgUnit).where(OrgUnit.code == "PADER"))
    programme = session.scalar(select(Programme).where(Programme.code == "MNCH"))
    session.add(
        SourceMapping(
            internal_source_key="ANC1",
            programme_id=programme.id,
            dhis2_item_uid="TEST_UID_ANC1",
            mapping_version="v1",
            enabled=True,
        )
    )
    # Give the job a provable geography scope so coverage is the only thing missing.
    session.add(OrgUnitMapping(org_unit_id=pader.id, source_system="dhis2", external_uid="TEST_UID_UG"))
    session.flush()

    job = enqueue_sync_job(
        session,
        org_unit=pader,
        periods=["202407"],
        user=None,
        job_type=ConnectorType.AGGREGATE.value,
        programme_id=programme.id,
    )
    session.flush()
    executed = execute_sync_job(session, job.id)
    assert executed.status in {"succeeded", "partially_succeeded", "failed"}

    from sqlalchemy import select as sa_select

    from app.models import FreshnessSnapshot

    snapshot = session.scalar(sa_select(FreshnessSnapshot).where(FreshnessSnapshot.connector == "aggregate"))
    assert snapshot is not None
    coverage = snapshot.detail["mapping_coverage"]
    assert coverage["complete"] is False
    assert coverage["resolved_count"] == 1
    assert "ANC4" in coverage["unresolved_source_keys"]
    # The attempt genuinely succeeded; what must not be claimed is that the programme is usable.
    assert snapshot.detail["programme_ready"] is False

"""Population staging: production-unresolved semantics, idempotent batches and the review transition.

Corrective work package G. Synthetic workbooks and organisation units only; no official
population values are used and nothing is approved.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.config import get_settings
from app.domain.enums import OrgUnitLevel
from app.models import (
    AuditLog,
    PopulationImportBatch,
    PopulationImportRow,
    PopulationValue,
    PopulationVersion,
)
from app.services.authorization import AuthorizationError
from app.services.geography import create_org_unit
from app.services.population_workbook import (
    REFERENCE_AUTHORITATIVE,
    REFERENCE_SYNTHETIC,
    REFERENCE_UNAPPROVED,
    REVIEW_PENDING,
    REVIEW_REJECTED,
    REVIEW_REVIEWED,
    PopulationWorkbookError,
    crosswalk_semantics,
    detect_reference_scope,
    reconcile_workbook,
    reference_fingerprint,
    review_staged_batch,
    stage_population_workbook,
)
from scripts.import_population_workbook import _markdown, _payload
from tests.test_population_workbook import SYNTHETIC, _grant, _quiet_read, _unit, _user, _write_workbook

FULL_COHORT = 146


def _full_cohort(session) -> list[tuple]:
    """146 synthetic district units and a matching synthetic workbook row for each."""
    uganda = _unit(session, "UG")
    rows = []
    for index in range(FULL_COHORT):
        name = f"Synthetic District {index:03d}"
        create_org_unit(
            session, code=f"TEST_SYN_{index:03d}", name=name, level_type=OrgUnitLevel.DISTRICT, parent=uganda
        )
        rows.append((name, "District", "Northern", [1_000 + index] * 7))
    session.commit()
    return rows


def _report(session, tmp_path, units=SYNTHETIC):
    """Reconcile a synthetic workbook. The file is written once per test and then re-read, because
    openpyxl embeds a timestamp and a rewritten file would have a different checksum."""
    path = tmp_path / "staging.xlsx"
    if not path.exists():
        _write_workbook(path, units)
    from app.services.population_workbook import file_sha256

    return reconcile_workbook(session, _quiet_read(path, expected_sha256=file_sha256(path)))


def _importer(session):
    return _grant(session, "pader.focal", "edit_population")


def _reviewer(session):
    return _grant(session, "national.analyst", "approve_population")


# ---------------------------------------------------------------------------
# Production-unresolved semantics
# ---------------------------------------------------------------------------


def test_synthetic_matches_are_candidates_and_every_unit_stays_production_unresolved(session, tmp_path):
    report = _report(session, tmp_path)
    scope = detect_reference_scope(session)
    assert scope == REFERENCE_SYNTHETIC
    semantics = crosswalk_semantics(report, scope)
    matched = sum(1 for item in report.units if item.status in {"matched_exact", "matched_alias"})
    assert matched >= 1
    assert semantics["reconciliation_matched"] == matched
    assert semantics["reconciliation_unmatched"] == len(SYNTHETIC) - matched
    assert semantics["production_unresolved"] == len(SYNTHETIC)
    assert semantics["production_resolved"] == 0
    assert len(semantics["non_production_candidates"]) == matched
    assert all(item["non_production_candidate"] is True for item in semantics["non_production_candidates"])


def test_a_full_but_unapproved_hierarchy_still_resolves_nothing(session, tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "population_hierarchy_approval_reference", "")
    rows = _full_cohort(session)
    report = _report(session, tmp_path, rows)
    scope = detect_reference_scope(session)
    assert scope == REFERENCE_UNAPPROVED
    semantics = crosswalk_semantics(report, scope)
    assert semantics["reconciliation_unmatched"] == 0
    assert semantics["production_unresolved"] == FULL_COHORT
    assert len(semantics["non_production_candidates"]) == FULL_COHORT


def test_only_an_authoritative_approved_hierarchy_reduces_production_unresolved(session, tmp_path, monkeypatch):
    rows = _full_cohort(session)
    monkeypatch.setattr(get_settings(), "population_hierarchy_approval_reference", "TEST-HIERARCHY-APPROVAL")
    report = _report(session, tmp_path, rows[:-1] + [("Not In Hierarchy", "District", "Northern", [5] * 7)])
    scope = detect_reference_scope(session)
    assert scope == REFERENCE_AUTHORITATIVE
    semantics = crosswalk_semantics(report, scope)
    assert semantics["production_resolved"] == FULL_COHORT - 1
    assert semantics["production_unresolved"] == 1
    assert semantics["non_production_candidates"] == []


def test_generated_report_distinguishes_reconciliation_from_production(session, tmp_path):
    report = _report(session, tmp_path)
    payload = _payload(session, report, display_name="synthetic.xlsx")
    assert payload["reference_scope"] == REFERENCE_SYNTHETIC
    assert payload["production_unresolved"] == len(SYNTHETIC)
    assert payload["reconciliation_unmatched"] < payload["production_unresolved"]
    markdown = _markdown(payload)
    assert f"**Production unresolved** | **{len(SYNTHETIC)}** of {len(SYNTHETIC)}" in markdown
    assert "Non-production candidates" in markdown and "(non-production candidate)" in markdown


# ---------------------------------------------------------------------------
# Idempotent staging
# ---------------------------------------------------------------------------


def test_restaging_the_same_identity_reuses_the_governed_batch(session, tmp_path):
    importer = _importer(session)
    report = _report(session, tmp_path)
    first = stage_population_workbook(session, importer, report=report)
    session.commit()
    second = stage_population_workbook(session, importer, report=_report(session, tmp_path))
    session.commit()
    assert first.reused is False and second.reused is True
    assert second.batch.id == first.batch.id
    assert session.scalar(select(func.count()).select_from(PopulationImportBatch)) == 1
    assert session.scalar(select(func.count()).select_from(PopulationImportRow)) == len(SYNTHETIC) * 7
    assert first.batch.reference_fingerprint == reference_fingerprint(session)
    assert session.scalar(select(func.count()).where(AuditLog.action == "population_workbook_staged")) == 1


def test_a_changed_reference_hierarchy_creates_a_new_batch(session, tmp_path):
    importer = _importer(session)
    first = stage_population_workbook(session, importer, report=_report(session, tmp_path))
    session.commit()
    create_org_unit(
        session,
        code="TEST_NEW_DISTRICT",
        name="Manafwa",
        level_type=OrgUnitLevel.DISTRICT,
        parent=_unit(session, "TESO"),
    )
    session.commit()
    second = stage_population_workbook(session, importer, report=_report(session, tmp_path))
    session.commit()
    assert second.reused is False and second.batch.id != first.batch.id
    assert second.batch.reference_fingerprint != first.batch.reference_fingerprint


def test_staging_creates_no_population_version_or_value(session, tmp_path):
    stage_population_workbook(session, _importer(session), report=_report(session, tmp_path))
    session.commit()
    assert session.scalar(select(func.count()).select_from(PopulationVersion)) == 0
    assert session.scalar(select(func.count()).select_from(PopulationValue)) == 0


def test_staging_requires_the_population_permission(session, tmp_path):
    with pytest.raises(AuthorizationError):
        stage_population_workbook(session, _user(session, "view.only"), report=_report(session, tmp_path))


# ---------------------------------------------------------------------------
# Review transition
# ---------------------------------------------------------------------------


def _staged(session, tmp_path, units=SYNTHETIC):
    outcome = stage_population_workbook(session, _importer(session), report=_report(session, tmp_path, units))
    session.commit()
    return outcome.batch


def test_a_synthetic_batch_can_be_rejected_but_never_marked_reviewed(session, tmp_path):
    batch = _staged(session, tmp_path)
    reviewer = _reviewer(session)
    with pytest.raises(PopulationWorkbookError) as refused:
        review_staged_batch(session, reviewer, batch, decision=REVIEW_REVIEWED, reason="Looks right")
    assert refused.value.code == "authoritative_hierarchy_required"
    assert batch.review_status == REVIEW_PENDING

    review_staged_batch(session, reviewer, batch, decision=REVIEW_REJECTED, reason="Synthetic reference only.")
    session.commit()
    assert batch.review_status == REVIEW_REJECTED and batch.reviewed_by_user_id == reviewer.id
    assert batch.reviewed_at is not None
    states = set(session.scalars(select(PopulationImportRow.review_state)).all())
    assert states == {REVIEW_REJECTED}
    audit = session.scalar(select(AuditLog).where(AuditLog.action == "population_import_batch_reviewed"))
    assert audit.after_json["review_status"] == REVIEW_REJECTED
    with pytest.raises(PopulationWorkbookError) as again:
        review_staged_batch(session, reviewer, batch, decision=REVIEW_REJECTED, reason="Twice")
    assert again.value.code == "batch_already_reviewed"


def test_review_needs_a_second_person_a_reason_and_the_approval_permission(session, tmp_path):
    batch = _staged(session, tmp_path)
    importer = _user(session, "pader.focal")
    _grant(session, "pader.focal", "approve_population")
    with pytest.raises(PopulationWorkbookError) as self_review:
        review_staged_batch(session, importer, batch, decision=REVIEW_REJECTED, reason="Mine")
    assert self_review.value.code == "second_reviewer_required"
    with pytest.raises(AuthorizationError):
        review_staged_batch(session, _user(session, "view.only"), batch, decision=REVIEW_REJECTED, reason="No")
    reviewer = _reviewer(session)
    with pytest.raises(PopulationWorkbookError) as no_reason:
        review_staged_batch(session, reviewer, batch, decision=REVIEW_REJECTED, reason="  ")
    assert no_reason.value.code == "reason_required"
    with pytest.raises(PopulationWorkbookError) as bad:
        review_staged_batch(session, reviewer, batch, decision="approved", reason="x")
    assert bad.value.code == "invalid_review_decision"


def test_a_fully_resolved_authoritative_batch_can_be_reviewed_without_creating_populations(
    session, tmp_path, monkeypatch
):
    rows = _full_cohort(session)
    monkeypatch.setattr(get_settings(), "population_hierarchy_approval_reference", "TEST-HIERARCHY-APPROVAL")
    batch = _staged(session, tmp_path, rows)
    assert batch.reference_scope == REFERENCE_AUTHORITATIVE
    review_staged_batch(session, _reviewer(session), batch, decision=REVIEW_REVIEWED, reason="Crosswalk checked.")
    session.commit()
    assert batch.review_status == REVIEW_REVIEWED
    assert session.scalar(select(func.count()).select_from(PopulationVersion)) == 0


def test_an_authoritative_batch_with_unresolved_units_cannot_be_reviewed(session, tmp_path, monkeypatch):
    rows = _full_cohort(session)
    monkeypatch.setattr(get_settings(), "population_hierarchy_approval_reference", "TEST-HIERARCHY-APPROVAL")
    batch = _staged(session, tmp_path, rows[:-1] + [("Not In Hierarchy", "District", "Northern", [5] * 7)])
    with pytest.raises(PopulationWorkbookError) as refused:
        review_staged_batch(session, _reviewer(session), batch, decision=REVIEW_REVIEWED, reason="x")
    assert refused.value.code == "unresolved_units"

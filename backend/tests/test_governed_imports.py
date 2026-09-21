"""Approval packets must be explicit, two-person, atomic and idempotent."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.models import AuditLog, OrgUnit, OrgUnitMapping, SourceMapping, User
from app.services.governed_imports import (
    GovernedImportError,
    apply_hierarchy_packet,
    apply_source_mapping_packet,
)


def _users(session) -> tuple[User, User]:
    actor = session.scalar(select(User).where(User.username == "admin.user"))
    reviewer = User(
        username="second.admin",
        display_name="Second System Administrator",
        email="second_admin@dev.local",
        password_hash=actor.password_hash,
        is_active=True,
        is_system_admin=True,
        identity_provider="local_dev",
    )
    session.add(reviewer)
    session.flush()
    return actor, reviewer


def _hierarchy_packet() -> dict:
    return {
        "schema": "hpip.hierarchy-approval.v1",
        "approval_reference": "MOH-HIERARCHY-TEST-1",
        "rows": [
            {
                "code": "TEST_REGION",
                "name": "Reviewed Test Region",
                "level_type": "region",
                "parent_code": "UG",
                "dhis2_uid": "Abcdef12345",
                "review_status": "approved",
            },
            {
                "code": "TEST_DISTRICT",
                "name": "Reviewed Test District",
                "level_type": "district",
                "parent_code": "TEST_REGION",
                "dhis2_uid": "Bbcdef12345",
                "review_status": "approved",
            },
        ],
    }


def _source_packet() -> dict:
    return {
        "schema": "hpip.source-mapping-approval.v1",
        "approval_reference": "MOH-SOURCES-TEST-1",
        "rows": [
            {
                "internal_source_key": "ANC1",
                "approved_uid": "Cbcdef12345",
                "approved_item_kind": "data_element",
                "approved_aggregation_semantics": "SUM",
                "approved_category_option_combo": None,
                "programmes": ["MNCH"],
                "review_status": "approved",
                "candidates": [
                    {
                        "uid": "Cbcdef12345",
                        "item_kind": "data_element",
                        "requires_category_option_combo": False,
                    }
                ],
            }
        ],
    }


def test_hierarchy_packet_is_two_person_audited_and_idempotent(session):
    actor, reviewer = _users(session)
    packet = _hierarchy_packet()

    first = apply_hierarchy_packet(
        session,
        packet=packet,
        actor=actor,
        reviewer=reviewer,
        approval_reference="MOH-HIERARCHY-TEST-1",
    )
    second = apply_hierarchy_packet(
        session,
        packet=packet,
        actor=actor,
        reviewer=reviewer,
        approval_reference="MOH-HIERARCHY-TEST-1",
    )

    district = session.scalar(select(OrgUnit).where(OrgUnit.code == "TEST_DISTRICT"))
    assert first.created == 2 and first.unchanged == 0
    assert second.created == 0 and second.unchanged == 2
    assert district.path == "/UG/TEST_REGION/TEST_DISTRICT"
    assert session.scalar(select(func.count()).select_from(OrgUnitMapping)) == 2
    audit = session.scalar(
        select(AuditLog)
        .where(AuditLog.action == "approved_hierarchy_packet_applied")
        .order_by(AuditLog.created_at.desc())
    )
    assert audit.after_json["reviewed_by_user_id"] == str(reviewer.id)
    assert audit.after_json["approval_reference"] == "MOH-HIERARCHY-TEST-1"


def test_hierarchy_packet_refuses_overlapping_external_uid(session):
    actor, reviewer = _users(session)
    apply_hierarchy_packet(
        session,
        packet=_hierarchy_packet(),
        actor=actor,
        reviewer=reviewer,
        approval_reference="MOH-HIERARCHY-TEST-1",
    )
    packet = {
        "schema": "hpip.hierarchy-approval.v1",
        "approval_reference": "MOH-HIERARCHY-TEST-2",
        "rows": [
            {
                "code": "OTHER_REGION",
                "name": "Other Region",
                "level_type": "region",
                "parent_code": "UG",
                "dhis2_uid": "Abcdef12345",
                "review_status": "approved",
            }
        ],
    }
    savepoint = session.begin_nested()
    try:
        try:
            apply_hierarchy_packet(
                session,
                packet=packet,
                actor=actor,
                reviewer=reviewer,
                approval_reference="MOH-HIERARCHY-TEST-2",
            )
        except GovernedImportError as exc:
            assert exc.code == "org_mapping_overlap"
        else:  # pragma: no cover - explicit regression failure message
            raise AssertionError("Overlapping external UID was accepted.")
    finally:
        savepoint.rollback()
    assert session.scalar(select(OrgUnit).where(OrgUnit.code == "OTHER_REGION")) is None


def test_source_mapping_packet_stays_incomplete_until_every_formula_key_is_approved(session):
    actor, reviewer = _users(session)
    packet = _source_packet()

    first = apply_source_mapping_packet(
        session,
        packet=packet,
        actor=actor,
        reviewer=reviewer,
        approval_reference="MOH-SOURCES-TEST-1",
        mapping_version="approved-test-v1",
    )
    second = apply_source_mapping_packet(
        session,
        packet=packet,
        actor=actor,
        reviewer=reviewer,
        approval_reference="MOH-SOURCES-TEST-1",
        mapping_version="approved-test-v1",
    )

    assert first.created == 1 and first.coverage["MNCH"]["complete"] is False
    assert first.coverage["MNCH"]["resolved_count"] == 1
    assert second.created == 0 and second.unchanged == 1
    mapping = session.scalar(
        select(SourceMapping).where(
            SourceMapping.internal_source_key == "ANC1",
            SourceMapping.mapping_version == "approved-test-v1",
        )
    )
    assert mapping.dhis2_item_uid == "Cbcdef12345"


def test_packets_refuse_self_approval_and_unapproved_rows(session):
    actor, reviewer = _users(session)
    packet = _hierarchy_packet()
    try:
        apply_hierarchy_packet(
            session,
            packet=packet,
            actor=actor,
            reviewer=actor,
            approval_reference="MOH-HIERARCHY-TEST-1",
        )
    except GovernedImportError as exc:
        assert exc.code == "separation_of_duties_required"
    else:  # pragma: no cover
        raise AssertionError("Self-approval was accepted.")

    packet["rows"][0]["review_status"] = "unreviewed"
    try:
        apply_hierarchy_packet(
            session,
            packet=packet,
            actor=actor,
            reviewer=reviewer,
            approval_reference="MOH-HIERARCHY-TEST-1",
        )
    except GovernedImportError as exc:
        assert exc.code == "unapproved_row"
    else:  # pragma: no cover
        raise AssertionError("An unreviewed row was accepted.")


def test_source_packet_refuses_unimplemented_semantics_and_invalid_category_uid(session):
    actor, reviewer = _users(session)
    packet = _source_packet()
    packet["rows"][0]["approved_aggregation_semantics"] = "MEDIAN"
    with pytest.raises(GovernedImportError) as invalid_semantics:
        apply_source_mapping_packet(
            session,
            packet=packet,
            actor=actor,
            reviewer=reviewer,
            approval_reference="MOH-SOURCES-TEST-1",
            mapping_version="approved-test-v1",
        )
    assert invalid_semantics.value.code == "mapping_semantics_missing"

    packet["rows"][0]["approved_aggregation_semantics"] = "SUM"
    packet["rows"][0]["approved_category_option_combo"] = "not-a-dhis2-uid"
    with pytest.raises(GovernedImportError) as invalid_coc:
        apply_source_mapping_packet(
            session,
            packet=packet,
            actor=actor,
            reviewer=reviewer,
            approval_reference="MOH-SOURCES-TEST-1",
            mapping_version="approved-test-v1",
        )
    assert invalid_coc.value.code == "invalid_category_option_combo"

    packet["rows"][0]["approved_category_option_combo"] = "Abcdef12345"
    packet["rows"][0]["approved_item_kind"] = "indicator"
    packet["rows"][0]["candidates"][0]["item_kind"] = "indicator"
    with pytest.raises(GovernedImportError) as invalid_operand:
        apply_source_mapping_packet(
            session,
            packet=packet,
            actor=actor,
            reviewer=reviewer,
            approval_reference="MOH-SOURCES-TEST-1",
            mapping_version="approved-test-v1",
        )
    assert invalid_operand.value.code == "category_option_combo_item_kind"

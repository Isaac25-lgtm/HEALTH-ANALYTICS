"""Boundary authority and geometry activation governance.

A name match is never a production boundary mapping unless the hierarchy for that level is
owner-approved (a recorded reference) and complete, the mapping is unambiguous, and the effective
date and mapping decision have recorded approval references. No real boundary is activated here.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import func, select

from app.config import get_settings
from app.domain.enums import OrgUnitLevel
from app.models import AuditLog, Geometry, OrgUnit, User
from app.services.authorization import AuthorizationError
from app.services.geography import create_org_unit
from app.services.geometry import (
    apply_geometry_import,
    boundary_authority,
    boundary_crosswalk_semantics,
    build_map_block,
    prepare_geometry_import,
    snapshot_map_features,
)
from app.services.hierarchy_authority import (
    REFERENCE_AUTHORITATIVE,
    REFERENCE_SYNTHETIC,
    REFERENCE_UNAPPROVED,
)
from tests import boundary_fixtures as fx

VALID_FROM = date(2031, 1, 1)


def _user(session, username="admin.user"):
    return session.scalar(select(User).where(User.username == username))


def _unit(session, code):
    return session.scalar(select(OrgUnit).where(OrgUnit.code == code))


def _activate(session, plan, **overrides):
    arguments = {
        "valid_from": VALID_FROM,
        "effective_date_verified": True,
        "effective_date_reference": fx.EFFECTIVE_DATE_REFERENCE,
        "mapping_decision_reference": fx.MAPPING_REFERENCE,
    }
    arguments.update(overrides)
    user = arguments.pop("user", None) or _user(session)
    return apply_geometry_import(session, user, plan, **arguments)


@pytest.fixture()
def approved(monkeypatch):
    monkeypatch.setattr(get_settings(), "boundary_district_hierarchy_approval_reference", fx.APPROVAL)


def _geometry_count(session) -> int:
    return int(session.scalar(select(func.count()).select_from(Geometry)) or 0)


# ---------------------------------------------------------------------------
# Crosswalk semantics
# ---------------------------------------------------------------------------


def test_synthetic_matches_remain_production_unresolved_and_cannot_activate(session, tmp_path, approved):
    source = fx.write_geojson(tmp_path / "synthetic.geojson", ["Pader", "Kitgum", "Soroti", "Nowhere District"])
    plan = prepare_geometry_import(session, source, "district")
    semantics = boundary_crosswalk_semantics(plan, boundary_authority(session, plan))
    assert semantics["reference_scope"] == REFERENCE_SYNTHETIC
    assert semantics["source_features"] == 4
    assert semantics["reconciliation_matched"] == 3
    assert semantics["reconciliation_unmatched"] == 1
    assert semantics["production_resolved"] == 0
    assert semantics["production_unresolved"] == 4
    assert semantics["non_production_candidates"] == ["Kitgum", "Pader", "Soroti"]
    with pytest.raises(AuthorizationError) as refused:
        _activate(session, plan, allow_unmatched=True, partial_activation_reference=fx.PARTIAL_REFERENCE)
    assert refused.value.code == "boundary_hierarchy_not_approved"
    assert _geometry_count(session) == 0


def test_a_full_but_unapproved_hierarchy_resolves_nothing(session, tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "boundary_district_hierarchy_approval_reference", "")
    names = fx.create_cohort(session)
    plan = prepare_geometry_import(session, fx.write_geojson(tmp_path / "full.geojson", names), "district")
    semantics = boundary_crosswalk_semantics(plan, boundary_authority(session, plan))
    assert semantics["reference_scope"] == REFERENCE_UNAPPROVED
    assert semantics["reconciliation_matched"] == 146
    assert semantics["production_resolved"] == 0 and semantics["production_unresolved"] == 146
    assert len(semantics["non_production_candidates"]) == 146
    with pytest.raises(AuthorizationError) as refused:
        _activate(session, plan)
    assert refused.value.code == "boundary_hierarchy_not_approved"


def test_population_approval_does_not_approve_boundaries(session, tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "population_hierarchy_approval_reference", "TEST-POPULATION-ONLY")
    monkeypatch.setattr(get_settings(), "boundary_district_hierarchy_approval_reference", "")
    names = fx.create_cohort(session)
    plan = prepare_geometry_import(session, fx.write_geojson(tmp_path / "full.geojson", names), "district")
    with pytest.raises(AuthorizationError) as refused:
        _activate(session, plan)
    assert refused.value.code == "boundary_hierarchy_not_approved"


def test_sub_county_authority_is_separate_and_fails_closed(session, tmp_path, approved):
    source = fx.write_geojson(
        tmp_path / "subcounties.geojson", ["Pader Town"], property_name="Sub_County", extra={"District": "Pader"}
    )
    plan = prepare_geometry_import(session, source, "sub_county")
    authority = boundary_authority(session, plan)
    semantics = boundary_crosswalk_semantics(plan, authority)
    assert semantics["reconciliation_matched"] == 1
    assert authority.reference_scope == REFERENCE_UNAPPROVED
    assert semantics["production_unresolved"] == 1 and semantics["non_production_candidates"] == ["Pader Town"]
    with pytest.raises(AuthorizationError) as refused:
        _activate(session, plan)
    assert refused.value.code == "boundary_hierarchy_not_approved"


# ---------------------------------------------------------------------------
# Activation gate
# ---------------------------------------------------------------------------


def test_approved_complete_mapping_activates_with_a_full_audit(session, tmp_path, approved):
    names = fx.create_cohort(session)
    plan = prepare_geometry_import(session, fx.write_geojson(tmp_path / "full.geojson", names), "district")
    semantics = boundary_crosswalk_semantics(plan, boundary_authority(session, plan))
    assert semantics["reference_scope"] == REFERENCE_AUTHORITATIVE
    assert semantics["production_resolved"] == 146 and semantics["production_unresolved"] == 0
    result = _activate(session, plan)
    session.commit()
    assert result == {"inserted": 146, "unchanged": 0, "superseded": 0}
    audit = session.scalar(select(AuditLog).where(AuditLog.action == "geometry_imported"))
    assert audit.actor_user_id == _user(session).id and audit.created_at is not None
    after = audit.after_json
    assert after["source_file"] == "full.geojson"
    assert after["source_sha256"] == plan.source_sha256 and len(after["source_sha256"]) == 64
    assert after["level_type"] == "district"
    assert after["hierarchy_approval_reference"] == fx.APPROVAL
    assert after["mapping_decision_reference"] == fx.MAPPING_REFERENCE
    assert after["effective_date"] == VALID_FROM.isoformat()
    assert after["effective_date_reference"] == fx.EFFECTIVE_DATE_REFERENCE
    assert (after["inserted"], after["unchanged"], after["superseded"]) == (146, 0, 0)
    again = _activate(session, prepare_geometry_import(session, tmp_path / "full.geojson", "district"))
    assert again == {"inserted": 0, "unchanged": 146, "superseded": 0}


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"effective_date_reference": None}, "boundary_effective_date_unverified"),
        ({"effective_date_reference": "  "}, "boundary_effective_date_unverified"),
        ({"effective_date_verified": False}, "boundary_effective_date_unverified"),
        ({"mapping_decision_reference": None}, "boundary_mapping_decision_missing"),
    ],
)
def test_missing_effective_date_or_mapping_approval_blocks_activation(session, tmp_path, approved, overrides, code):
    names = fx.create_cohort(session)
    plan = prepare_geometry_import(session, fx.write_geojson(tmp_path / "full.geojson", names), "district")
    with pytest.raises(AuthorizationError) as refused:
        _activate(session, plan, **overrides)
    assert refused.value.code == code
    assert _geometry_count(session) == 0


def test_allow_unmatched_needs_a_partial_activation_reference_and_never_bypasses_approval(session, tmp_path, approved):
    names = fx.create_cohort(session)
    source = fx.write_geojson(tmp_path / "partial.geojson", [*names, "Unmapped Feature"])
    plan = prepare_geometry_import(session, source, "district")
    with pytest.raises(AuthorizationError) as incomplete:
        _activate(session, plan)
    assert incomplete.value.code == "boundary_mapping_incomplete"
    with pytest.raises(AuthorizationError) as unapproved:
        _activate(session, plan, allow_unmatched=True)
    assert unapproved.value.code == "boundary_partial_activation_unapproved"
    assert _geometry_count(session) == 0
    result = _activate(session, plan, allow_unmatched=True, partial_activation_reference=fx.PARTIAL_REFERENCE)
    assert result["inserted"] == 146


def test_wrong_geography_level_is_rejected(session, tmp_path, approved):
    names = fx.create_cohort(session)
    plan = prepare_geometry_import(session, fx.write_geojson(tmp_path / "full.geojson", names), "district")
    moved = _unit(session, "TEST_BND_000")
    moved.level_type = OrgUnitLevel.SUB_COUNTY.value
    session.flush()
    with pytest.raises(AuthorizationError) as refused:
        _activate(session, plan)
    assert refused.value.code == "boundary_level_mismatch"
    assert _geometry_count(session) == 0


def test_duplicate_and_ambiguous_mappings_are_rejected(session, tmp_path, approved):
    names = fx.create_cohort(session)
    duplicate = prepare_geometry_import(
        session, fx.write_geojson(tmp_path / "duplicate.geojson", [*names, names[0]]), "district"
    )
    with pytest.raises(AuthorizationError) as refused:
        _activate(session, duplicate)
    assert refused.value.code == "boundary_mapping_ambiguous"
    create_org_unit(
        session, code="TEST_BND_TWIN", name=names[1], level_type=OrgUnitLevel.DISTRICT, parent=_unit(session, "UG")
    )
    session.commit()
    ambiguous = prepare_geometry_import(session, fx.write_geojson(tmp_path / "ambiguous.geojson", names), "district")
    assert ambiguous.ambiguous
    with pytest.raises(AuthorizationError) as refused_again:
        _activate(session, ambiguous)
    assert refused_again.value.code == "boundary_mapping_ambiguous"
    assert _geometry_count(session) == 0


def test_activation_requires_manage_mappings_and_a_checksum(session, tmp_path, approved):
    names = fx.create_cohort(session)
    plan = prepare_geometry_import(session, fx.write_geojson(tmp_path / "full.geojson", names), "district")
    with pytest.raises(AuthorizationError) as forbidden:
        _activate(session, plan, user=_user(session, "national.analyst"))
    assert forbidden.value.code == "forbidden_action"
    plan.source_sha256 = ""
    with pytest.raises(AuthorizationError) as unchecked:
        _activate(session, plan)
    assert unchecked.value.code == "boundary_checksum_missing"
    assert _geometry_count(session) == 0


# ---------------------------------------------------------------------------
# Map payload: only snapshot units, one boundary level
# ---------------------------------------------------------------------------


def test_map_payload_contains_only_snapshot_units_at_one_level(session):
    square = {"type": "Polygon", "coordinates": [[[32, 2], [33, 2], [33, 3], [32, 2]]]}
    for code in ("PADER", "KITGUM", "SOROTI", "ACHOLI"):
        session.add(Geometry(org_unit_id=_unit(session, code).id, geojson=square, valid_from=date(2020, 1, 1)))
    session.commit()
    user = _user(session, "national.analyst")
    rows = [
        {"org_unit_id": str(_unit(session, code).id), "values": {"ANC1_COVERAGE": {"raw_value": 50.0}}}
        for code in ("PADER", "KITGUM")
    ]
    block = build_map_block(
        session,
        user,
        parent=_unit(session, "ACHOLI"),
        value_rows=rows,
        indicator_code="ANC1_COVERAGE",
        effective_date=date(2025, 1, 1),
    )
    assert block["map_state"] == "mapped" and block["map_level_types"] == ["district"]
    payload = snapshot_map_features(session, user, map_block=block, value_rows=rows)
    assert {feature["properties"]["code"] for feature in payload["features"]} == {"PADER", "KITGUM"}
    assert {feature["properties"]["level_type"] for feature in payload["features"]} == {"district"}

    regions = [{"org_unit_id": str(_unit(session, "ACHOLI").id), "values": {}}]
    region_block = build_map_block(
        session,
        user,
        parent=_unit(session, "UG"),
        value_rows=regions,
        indicator_code="ANC1_COVERAGE",
        effective_date=date(2025, 1, 1),
    )
    # Region geometry exists here, so it maps as a region; districts are never substituted for it.
    region_payload = snapshot_map_features(session, user, map_block=region_block, value_rows=regions)
    assert {feature["properties"]["level_type"] for feature in region_payload["features"]} == {"sub_region"}

    scoped_user = _user(session, "pader.focal")
    scoped_block = build_map_block(
        session,
        scoped_user,
        parent=_unit(session, "ACHOLI"),
        value_rows=rows,
        indicator_code="ANC1_COVERAGE",
        effective_date=date(2025, 1, 1),
    )
    assert scoped_block["map_feature_org_unit_ids"] == [str(_unit(session, "PADER").id)]


def test_reconciliation_report_uses_production_semantics(session, tmp_path):
    from scripts.geojson_reconciliation import CANDIDATES, _markdown, analyse, crosswalk

    spec = next(item for item in CANDIDATES if item["file"] == "UGANDA_DISTRICT.json")
    path = fx.write_geojson(tmp_path / spec["file"], ["Pader", "Kitgum", "Soroti", "Elsewhere One", "Elsewhere Two"])
    data = crosswalk(session, spec, path)
    assert data["reconciliation_matched"] == 3 and data["reconciliation_unmatched"] == 2
    assert data["production_resolved"] == 0 and data["production_unresolved"] == 5
    assert data["non_production_candidates"] == ["Kitgum", "Pader", "Soroti"]
    assert data["hierarchy_approval_reference"] is None
    item = analyse(path, spec).as_dict()
    item["crosswalk"] = data
    markdown = _markdown({"generated_at": "test", "effective_date_status": "not verified", "candidates": [item]})
    assert "| **`production_unresolved`** | **5** |" in markdown
    assert "Non-production candidates" in markdown

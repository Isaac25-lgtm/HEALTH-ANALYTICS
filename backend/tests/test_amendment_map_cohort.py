"""Amendment §13: the map renders exactly the authorised value rows, with level-true geometry."""

from datetime import date

from sqlalchemy import select

from app.models import Geometry, OrgUnit, User
from app.services.geometry import build_map_block
from tests.conftest import auth_header, login, query_dashboard
from tests.helpers import put_raw

SQUARE = {"type": "Polygon", "coordinates": [[[32.0, 3.0], [32.1, 3.0], [32.1, 3.1], [32.0, 3.1], [32.0, 3.0]]]}


def _unit(session, code):
    return session.scalar(select(OrgUnit).where(OrgUnit.code == code))


def _geometry(session, unit, *, kind="polygon", valid_from=date(2020, 1, 1), valid_to=None, geojson=None):
    row = Geometry(
        org_unit_id=unit.id,
        geojson=geojson or SQUARE,
        geometry_kind=kind,
        source="TEST_SYNTHETIC_BOUNDARY",
        valid_from=valid_from,
        valid_to=valid_to,
    )
    session.add(row)
    session.flush()
    return row


def _district_geometries(session):
    for code in ("PADER", "KITGUM", "SOROTI"):
        _geometry(session, _unit(session, code))


def _seed_first_trimester(session):
    for code, first, total in (("PADER", 30, 100), ("KITGUM", 45, 100)):
        unit = _unit(session, code)
        put_raw(session, unit, "FY2024/25", "ANC1_FT", first)
        put_raw(session, unit, "FY2024/25", "ANC1", total)


def test_national_map_never_substitutes_district_polygons_for_regions(client, session):
    _district_geometries(session)
    session.commit()
    headers = auth_header(login(client, "national.analyst"))
    body = query_dashboard(client, headers, _unit(session, "UG").id).json()
    block = body["map"]
    assert block["map_state"] == "geometry_unavailable_for_level"
    assert block["map_level"] == "region_equivalent"
    assert block["map_feature_org_unit_ids"] == []
    assert set(block["missing_geometry_ids"]) == {str(_unit(session, "ACHOLI").id), str(_unit(session, "TESO").id)}
    assert "not substituted" in block["mapping_note"]
    features = client.get(f"/analysis-snapshots/{body['analysis_snapshot_id']}/map-features", headers=headers).json()
    assert features["features"] == []
    assert features["map_state"] == "geometry_unavailable_for_level"


def test_regional_map_features_match_the_value_rows_one_to_one(client, session):
    _district_geometries(session)
    _seed_first_trimester(session)
    session.commit()
    headers = auth_header(login(client, "acholi.analyst"))
    body = query_dashboard(
        client, headers, _unit(session, "ACHOLI").id, selected_indicator="ANC1_FIRST_TRIMESTER"
    ).json()
    block = body["map"]
    rows = {row["org_unit_id"]: row for row in body["module_result"]["org_unit_comparison"]}
    assert block["map_state"] == "mapped"
    assert block["map_level"] == "district_equivalent"
    assert block["selected_indicator"] == "ANC1_FIRST_TRIMESTER"
    assert block["geometry_effective_date"] == "2025-06-30"
    assert sorted(block["map_feature_org_unit_ids"]) == sorted(rows)
    assert block["map_value_run_ids"] == {key: row["calculation_run_id"] for key, row in rows.items()}
    assert set(block["geometry_versions"]) == set(rows)
    features = client.get(f"/analysis-snapshots/{body['analysis_snapshot_id']}/map-features", headers=headers).json()
    assert features["feature_count"] == len(rows) == 2
    soroti = str(_unit(session, "SOROTI").id)
    for feature in features["features"]:
        row = rows[feature["id"]]
        value = row["values"]["ANC1_FIRST_TRIMESTER"]
        assert feature["id"] != soroti
        assert feature["properties"]["raw_value"] == value["raw_value"]
        assert feature["properties"]["calculation_run_id"] == row["calculation_run_id"]


def test_district_screen_maps_facility_points_not_the_district_polygon(client, session):
    _district_geometries(session)
    facility = _unit(session, "PADER_HC_III")
    _geometry(session, facility, kind="point", geojson={"type": "Point", "coordinates": [32.05, 3.05]})
    session.commit()
    headers = auth_header(login(client, "pader.focal"))
    body = query_dashboard(client, headers, _unit(session, "PADER").id).json()
    block = body["map"]
    assert block["map_level"] == "facility"
    assert block["map_feature_org_unit_ids"] == [str(facility.id)]
    features = client.get(f"/analysis-snapshots/{body['analysis_snapshot_id']}/map-features", headers=headers).json()
    assert [feature["id"] for feature in features["features"]] == [str(facility.id)]
    assert features["features"][0]["geometry"]["type"] == "Point"


def test_geometry_is_selected_for_the_period_end(session):
    pader, kitgum = _unit(session, "PADER"), _unit(session, "KITGUM")
    _geometry(session, pader, valid_from=date(2015, 1, 1), valid_to=date(2019, 12, 31))
    current = _geometry(session, pader, valid_from=date(2020, 1, 1))
    _geometry(session, kitgum, valid_from=date(2025, 7, 1))
    admin = session.scalar(select(User).where(User.username == "admin.user"))
    rows = [
        {"org_unit_id": str(pader.id), "calculation_run_id": "run-pader", "values": {}},
        {"org_unit_id": str(kitgum.id), "calculation_run_id": "run-kitgum", "values": {}},
    ]
    block = build_map_block(
        session,
        admin,
        parent=_unit(session, "ACHOLI"),
        value_rows=rows,
        indicator_code="ANC1_COVERAGE",
        effective_date=date(2025, 6, 30),
    )
    assert block["map_feature_org_unit_ids"] == [str(pader.id)]
    assert block["geometry_versions"][str(pader.id)]["geometry_id"] == str(current.id)
    assert block["missing_geometry_ids"] == [str(kitgum.id)]
    assert set(block["missing_value_ids"]) == {str(pader.id), str(kitgum.id)}


def test_unauthorised_and_mixed_level_rows_are_not_mapped(session):
    _district_geometries(session)
    pader, kitgum, facility = _unit(session, "PADER"), _unit(session, "KITGUM"), _unit(session, "PADER_HC_III")
    focal = session.scalar(select(User).where(User.username == "pader.focal"))
    admin = session.scalar(select(User).where(User.username == "admin.user"))
    rows = [{"org_unit_id": str(unit.id), "values": {}} for unit in (pader, kitgum)]
    scoped = build_map_block(
        session, focal, parent=_unit(session, "ACHOLI"), value_rows=rows, indicator_code=None,
        effective_date=date(2025, 6, 30),
    )
    assert scoped["map_feature_org_unit_ids"] == [str(pader.id)]
    assert str(kitgum.id) not in scoped["missing_geometry_ids"] + scoped["missing_value_ids"]
    mixed = build_map_block(
        session,
        admin,
        parent=_unit(session, "ACHOLI"),
        value_rows=[*rows, {"org_unit_id": str(facility.id), "values": {}}],
        indicator_code=None,
        effective_date=date(2025, 6, 30),
    )
    assert mixed["map_state"] == "mixed_levels_not_mapped"
    assert mixed["map_feature_org_unit_ids"] == []

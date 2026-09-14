import json
from datetime import UTC, date, datetime
from uuid import UUID

import pytest
from sqlalchemy import select

from app.domain.enums import JobStatus
from app.integrations.dhis2.types import AggregateObservation
from app.models import (
    CalculatedValue,
    DataQualityFlag,
    Geometry,
    OrgUnit,
    PopulationVersion,
    Programme,
    RawAggregateValue,
    SourceMapping,
    SyncJob,
    User,
    UserPermission,
    UserProgrammeScope,
)
from app.services.authorization import AuthorizationError
from app.services.calculation import resolve_source_key, run_calculation
from app.services.geometry import apply_geometry_import, map_feature_collection, prepare_geometry_import
from app.services.population import approve_population_version, resolve_population
from app.services.quality import scan_quality
from app.services.sync import SyncDispatchError, persist_aggregate_observations
from tests.conftest import auth_header, login
from tests.helpers import map_ou, put_event, put_population, put_raw


def _unit(session, code: str) -> OrgUnit:
    return session.scalar(select(OrgUnit).where(OrgUnit.code == code))


def _programme(session, code: str) -> Programme:
    return session.scalar(select(Programme).where(Programme.code == code))


def _user(session, username: str) -> User:
    return session.scalar(select(User).where(User.username == username))


def test_zero_programme_scope_fails_closed_for_quality_and_sync(client, session):
    user = _user(session, "mnch.only")
    for scope in session.scalars(
        select(UserProgrammeScope).where(UserProgrammeScope.user_id == user.id)
    ).all():
        scope.is_active = False
    session.add(UserPermission(user_id=user.id, action="manage_sync"))
    programme = _programme(session, "MNCH")
    uganda = _unit(session, "UG")
    flag = DataQualityFlag(
        fingerprint="test-zero-programme-scope",
        rule_id="TEST_SCOPE",
        severity="WARNING",
        org_unit_id=uganda.id,
        programme_id=programme.id,
    )
    job = SyncJob(
        job_type="aggregate",
        status=JobStatus.SUCCEEDED.value,
        org_unit_id=uganda.id,
        programme_id=programme.id,
    )
    session.add_all([flag, job])
    session.commit()

    csrf = login(client, "mnch.only")
    assert client.get("/quality/flags", headers=auth_header(csrf)).json() == []
    assert client.get("/sync/jobs", headers=auth_header(csrf)).json() == []
    assert client.get(f"/quality/flags/{flag.id}", headers=auth_header(csrf)).status_code == 403
    assert client.get(f"/sync/jobs/{job.id}", headers=auth_header(csrf)).status_code == 403


def test_mpdsr_event_flags_are_programme_scoped_and_hidden_from_mnch(client, session):
    acholi = _unit(session, "ACHOLI")
    put_event(
        session,
        acholi,
        event_uid="TEST_UID_MPDSR_SCOPE",
        death_date=date(2024, 7, 10),
        notification_date=date(2024, 7, 9),
        data_values={"event_type": "maternal_notification"},
    )
    flags = scan_quality(session, org_unit=acholi, period="202407")
    mpdsr = _programme(session, "MPDSR")
    event_flags = [row for row in flags if row and row.event_uid]
    assert event_flags
    assert {row.programme_id for row in event_flags} == {mpdsr.id}
    session.commit()

    csrf = login(client, "mnch.only")
    response = client.get("/quality/flags", headers=auth_header(csrf))
    assert response.status_code == 200
    assert "TEST_UID_MPDSR_SCOPE" not in response.text
    assert all(row["rule_id"] != "NOTIFICATION_BEFORE_DEATH" for row in response.json())


def test_category_option_combo_selects_the_exact_mapping(session):
    uganda = _unit(session, "UG")
    programme = _programme(session, "MNCH")
    map_ou(session, uganda, "TEST_UID_UG_CATEGORY")
    mapping_a = SourceMapping(
        internal_source_key="TEST_CAT_A",
        programme_id=programme.id,
        dhis2_item_uid="TEST_UID_SHARED_CATEGORY",
        category_option_combo_uid="TEST_UID_COC_A",
        mapping_version="v1",
        enabled=True,
    )
    mapping_b = SourceMapping(
        internal_source_key="TEST_CAT_B",
        programme_id=programme.id,
        dhis2_item_uid="TEST_UID_SHARED_CATEGORY",
        category_option_combo_uid="TEST_UID_COC_B",
        mapping_version="v1",
        enabled=True,
    )
    job = SyncJob(
        job_type="aggregate",
        status=JobStatus.RUNNING.value,
        programme_id=programme.id,
        mapping_version="v1",
    )
    session.add_all([mapping_a, mapping_b, job])
    session.flush()
    observations = [
        AggregateObservation(
            org_unit_uid="TEST_UID_UG_CATEGORY",
            period="202407",
            item_uid="TEST_UID_SHARED_CATEGORY",
            category_option_combo_uid="TEST_UID_COC_A",
            value=11,
        ),
        AggregateObservation(
            org_unit_uid="TEST_UID_UG_CATEGORY",
            period="202407",
            item_uid="TEST_UID_SHARED_CATEGORY",
            category_option_combo_uid="TEST_UID_COC_B",
            value=22,
        ),
    ]
    persist_aggregate_observations(
        session,
        job,
        observations,
        {
            ("TEST_UID_SHARED_CATEGORY", "TEST_UID_COC_A"): mapping_a,
            ("TEST_UID_SHARED_CATEGORY", "TEST_UID_COC_B"): mapping_b,
        },
        datetime.now(UTC),
    )
    rows = session.scalars(
        select(RawAggregateValue).where(
            RawAggregateValue.source_metric_id == "TEST_UID_SHARED_CATEGORY"
        )
    ).all()
    assert {(row.internal_source_key, float(row.value)) for row in rows} == {
        ("TEST_CAT_A", 11),
        ("TEST_CAT_B", 22),
    }
    assert {row.programme_id for row in rows} == {programme.id}


def test_calculation_uses_actual_raw_mapping_lineage(session):
    uganda = _unit(session, "UG")
    programme = _programme(session, "MNCH")
    population = put_population(session, uganda, 2024, 10_000)
    unrelated = SourceMapping(
        internal_source_key="UNRELATED",
        programme_id=programme.id,
        dhis2_item_uid="TEST_UID_UNRELATED",
        mapping_version="v0_wrong",
        enabled=True,
    )
    actual = SourceMapping(
        internal_source_key="ANC1",
        programme_id=programme.id,
        dhis2_item_uid="TEST_UID_ANC1",
        mapping_version="v9_actual",
        enabled=True,
    )
    session.add_all([unrelated, actual])
    session.flush()
    raw = put_raw(session, uganda, "FY2024/25", "ANC1", 500, programme_id=programme.id)
    raw.mapping_version = "v9_actual"
    raw.source_freshness_at = datetime(2026, 1, 2, tzinfo=UTC)
    raw.provenance = {"mapping_id": str(actual.id)}
    session.flush()

    run = run_calculation(
        session,
        org_unit=uganda,
        period="FY2024/25",
        user=None,
        programme_codes=["MNCH"],
        indicator_codes=["ANC1_COVERAGE"],
    )
    value = session.scalar(select(CalculatedValue).where(CalculatedValue.calculation_run_id == run.id))
    assert value.mapping_version == "v9_actual"
    assert value.source_mapping_ids == [str(actual.id)]
    assert str(unrelated.id) not in (run.config_snapshot or {}).get("mapping_ids", [])
    assert (run.config_snapshot or {})["population_version_ids"] == [str(population.id)]
    assert (run.config_snapshot or {})["source_freshness_at"] == "2026-01-02T00:00:00+00:00"


def test_raw_aggregate_resolution_isolated_by_programme(session):
    uganda = _unit(session, "UG")
    mnch = _programme(session, "MNCH")
    mpdsr = _programme(session, "MPDSR")
    put_raw(session, uganda, "FY2024/25", "FRESH_SB", 5, programme_id=mnch.id)
    put_raw(session, uganda, "FY2024/25", "FRESH_SB", 99, programme_id=mpdsr.id)
    assert resolve_source_key(
        session, uganda, "FY2024/25", "FRESH_SB", programme_id=mnch.id
    ).value == 5
    assert resolve_source_key(
        session, uganda, "FY2024/25", "FRESH_SB", programme_id=mpdsr.id
    ).value == 99
    assert resolve_source_key(session, uganda, "FY2024/25", "FRESH_SB").status == "ambiguous_source"


def test_dispatch_failure_marks_committed_job_failed(client, session, monkeypatch):
    import app.api.routes.sync as sync_routes

    def fail_dispatch(_job_id):
        raise SyncDispatchError("Synthetic queue failure.")

    monkeypatch.setattr(sync_routes, "should_run_eager", lambda: False)
    monkeypatch.setattr(sync_routes, "dispatch_sync_job", fail_dispatch)
    csrf = login(client, "admin.user")
    response = client.post(
        "/sync/jobs",
        json={
            "org_unit_id": str(_unit(session, "UG").id),
            "period": "202407",
            "programme": "MNCH",
            "job_type": "aggregate",
        },
        headers=auth_header(csrf),
    )
    assert response.status_code == 503
    job = session.scalar(select(SyncJob).order_by(SyncJob.created_at.desc()))
    assert job.status == JobStatus.FAILED.value
    assert job.error_code == "sync_enqueue_failed"


def test_csrf_cookie_is_bound_to_its_session_token(client):
    first_csrf = login(client, "admin.user")
    first_session = client.cookies.get("hpip_session")
    second_csrf = login(client, "national.analyst")
    assert first_csrf != second_csrf
    client.cookies.set("hpip_session", first_session)
    client.cookies.set("hpip_csrf", second_csrf)
    assert client.post("/admin/probe", headers=auth_header(second_csrf)).status_code == 403


def test_population_import_api_draft_approval_and_resolution(client, session):
    pader = _unit(session, "PADER")
    editor_csrf = login(client, "pader.focal")
    imported = client.post(
        "/populations/import",
        json={
            "code": "TEST_OWNER_POP_2025",
            "name": "Owner population test",
            "source_name": "TEST_SOURCE_NOT_PRODUCTION",
            "population_type": "projection",
            "valid_from": "2024-01-01",
            "valid_to": "2026-12-31",
            "rows": [{"org_unit_code": "PADER", "year": 2025, "population": 12345}],
        },
        headers=auth_header(editor_csrf),
    )
    assert imported.status_code == 201, imported.text
    assert imported.json()["approval_status"] == "draft"
    version = session.get(PopulationVersion, UUID(imported.json()["id"]))
    assert resolve_population(session, pader, period_key="FY2025/26", version=version).status == "unavailable"
    assert client.get(
        f"/populations?org_unit_id={pader.id}&year=2025", headers=auth_header(editor_csrf)
    ).json() == []

    admin_csrf = login(client, "admin.user")
    approved = client.post(
        f"/populations/versions/{imported.json()['id']}/approve",
        json={"reason": "Synthetic approval test"},
        headers=auth_header(admin_csrf),
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["approval_status"] == "approved"
    listed = client.get(
        f"/populations?org_unit_id={pader.id}&year=2025", headers=auth_header(admin_csrf)
    )
    assert listed.status_code == 200
    assert listed.json()[0]["population"] == 12345


def test_population_importer_cannot_self_approve(session):
    editor = _user(session, "pader.focal")
    session.add(UserPermission(user_id=editor.id, action="approve_population"))
    version = put_population(session, _unit(session, "PADER"), 2025, 1, code="TEST_SELF_APPROVE")
    version.approval_status = "draft"
    version.imported_by_user_id = editor.id
    session.flush()
    try:
        approve_population_version(session, editor, version.id)
        raise AssertionError("self-approval should fail")
    except AuthorizationError as exc:
        assert exc.code == "forbidden_action"


def test_geojson_import_and_adaptive_map_contract(client, session, tmp_path):
    source = tmp_path / "districts.geojson"
    source.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"District": "Pader"},
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[[32, 2], [33, 2], [33, 3], [32, 2]]],
                        },
                    },
                    {
                        "type": "Feature",
                        "properties": {"District": "Kitgum"},
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[[33, 3], [34, 3], [34, 4], [33, 3]]],
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    plan = prepare_geometry_import(session, source, "district")
    assert plan.total_features == 2
    assert len(plan.records) == 2
    # Geometry never activates on an assumed effective date.
    with pytest.raises(AuthorizationError) as unverified:
        apply_geometry_import(session, _user(session, "admin.user"), plan, valid_from=date(2026, 1, 1))
    assert unverified.value.code == "boundary_effective_date_unverified"
    result = apply_geometry_import(
        session,
        _user(session, "admin.user"),
        plan,
        valid_from=date(2026, 1, 1),
        effective_date_verified=True,  # synthetic fixture date, declared explicitly by this test
    )
    assert result["inserted"] == 2
    session.commit()
    payload = map_feature_collection(
        session, _user(session, "national.analyst"), _unit(session, "ACHOLI")
    )
    assert payload["render_levels"] == ["district"]
    assert {feature["properties"]["code"] for feature in payload["features"]} == {
        "PADER",
        "KITGUM",
    }
    assert session.scalars(select(Geometry)).all()

    csrf = login(client, "national.analyst")
    response = client.get(f"/org-units/{_unit(session, 'ACHOLI').id}/map-geometry", headers=auth_header(csrf))
    assert response.status_code == 200
    assert response.json()["feature_count"] == 2
    district_csrf = login(client, "pader.focal")
    denied = client.get(
        f"/org-units/{_unit(session, 'ACHOLI').id}/map-geometry",
        headers=auth_header(district_csrf),
    )
    assert denied.status_code == 403

from datetime import UTC, date, datetime, timedelta

import httpx
from sqlalchemy import select

from app.domain.enums import ApprovalStatus, QualityStatus
from app.domain.periods import parse_period
from app.integrations.dhis2.aggregate import parse_analytics_rows
from app.integrations.dhis2.http import Dhis2HttpClient
from app.integrations.dhis2.tracker import TrackerEventsAdapter
from app.models import (
    CalculatedValue,
    DataQualityFlag,
    Indicator,
    OrgUnit,
    PopulationVersion,
    Programme,
    Role,
    SourceMapping,
    UserGeographyScope,
    UserProgrammeScope,
)
from app.services.calculation import evaluate_formula, resolve_source_key, run_calculation
from app.services.population import (
    approve_facility_population,
    enter_facility_population,
    reject_facility_population,
    resolve_population,
    resolve_population_year,
)
from app.services.quality import scan_quality
from app.services.sync import persist_aggregate_observations
from tests.conftest import auth_header, login
from tests.helpers import map_ou, map_source, put_event, put_population, put_raw


def _unit(session, code):
    return session.scalar(select(OrgUnit).where(OrgUnit.code == code))


def _user(session, username):
    from app.models import User

    return session.scalar(select(User).where(User.username == username))


def _eval(session, code, org="UG", period="FY2024/25"):
    indicator = session.scalar(select(Indicator).where(Indicator.code == code))
    from app.models import IndicatorVersion

    version = session.scalar(
        select(IndicatorVersion).where(
            IndicatorVersion.indicator_id == indicator.id, IndicatorVersion.is_current.is_(True)
        )
    )
    return evaluate_formula(
        session,
        org_unit=_unit(session, org),
        period=period,
        version=version,
        programme_id=indicator.programme_id,
    )


def test_mnch_only_omitting_programme_cannot_calculate_epi(client, session):
    token = login(client, "mnch.only")
    uganda = _unit(session, "UG")
    response = client.post(
        "/calculations/run",
        json={"org_unit_id": str(uganda.id), "period": "FY2024/25"},
        headers=auth_header(token),
    )
    assert response.status_code == 422


def test_mnch_only_cannot_request_mv4_indicator(client, session):
    token = login(client, "mnch.only")
    uganda = _unit(session, "UG")
    response = client.post(
        "/calculations/run",
        json={
            "org_unit_id": str(uganda.id),
            "period": "FY2024/25",
            "programme": "MNCH",
            "indicator_codes": ["MV4_COVERAGE"],
        },
        headers=auth_header(token),
    )
    assert response.status_code == 403


def test_unauthorised_calculation_run_uuid_is_denied(client, session):
    uganda = _unit(session, "UG")
    put_population(session, uganda, 2024, 10000)
    put_raw(session, uganda, "FY2024/25", "MV4", 10)
    national = login(client, "national.analyst")
    created = client.post(
        "/calculations/run",
        json={
            "org_unit_id": str(uganda.id),
            "period": "FY2024/25",
            "programme": "EPI",
            "indicator_codes": ["MV4_COVERAGE"],
        },
        headers=auth_header(national),
    )
    assert created.status_code == 200
    run_id = created.json()["id"]
    denied = client.get(f"/calculations/{run_id}", headers=auth_header(login(client, "mnch.only")))
    assert denied.status_code == 403
    national = login(client, "national.analyst")
    allowed = client.get(f"/calculations/{run_id}", headers=auth_header(national))
    assert allowed.status_code == 200
    pader = login(client, "pader.focal")
    geo_denied = client.get(f"/calculations/{run_id}", headers=auth_header(pader))
    assert geo_denied.status_code == 403


def test_ordinary_quality_response_redacts_nested_event_uids(client, session):
    acholi = _unit(session, "ACHOLI")
    put_event(
        session,
        acholi,
        event_uid="TEST_UID_EVENT_HIDDEN",
        death_date=date(2024, 7, 10),
        notification_date=date(2024, 7, 9),
        data_values={"event_type": "maternal_notification"},
        status="COMPLETED",
    )
    scan_quality(session, org_unit=acholi, period="202407")
    session.commit()
    token = login(client, "national.analyst")
    response = client.get("/quality/flags", headers=auth_header(token))
    assert response.status_code == 200
    payload = response.json()
    text = str(payload)
    assert "TEST_UID_EVENT" not in text
    assert "event_uids" not in text
    for row in payload:
        assert row.get("event_uid") in {None, ""}


def test_mpdsr_sensitive_flag_requires_permission(client, session):
    acholi = _unit(session, "ACHOLI")
    put_event(
        session,
        acholi,
        event_uid="TEST_UID_EVENT_SENS",
        death_date=date(2024, 7, 10),
        notification_date=date(2024, 7, 9),
        data_values={"event_type": "maternal_notification"},
        status="COMPLETED",
    )
    flags = scan_quality(session, org_unit=acholi, period="202407")
    session.commit()
    sensitive = next(flag for flag in flags if flag and flag.event_uid)
    ordinary = login(client, "national.analyst")
    denied = client.get(f"/quality/flags/{sensitive.id}", headers=auth_header(ordinary))
    assert denied.status_code == 403
    allowed = client.get(
        f"/quality/flags/{sensitive.id}",
        headers=auth_header(login(client, "mpdsr.analyst")),
    )
    assert allowed.status_code == 200
    assert allowed.json()["event_uid"] == "TEST_UID_EVENT_SENS"


def test_parent_plus_child_rows_are_never_double_counted(session):
    acholi = _unit(session, "ACHOLI")
    pader = _unit(session, "PADER")
    kitgum = _unit(session, "KITGUM")
    put_raw(session, acholi, "FY2024/25", "FRESH_SB", 50)
    put_raw(session, acholi, "FY2024/25", "MACERATED_SB", 0)
    put_raw(session, acholi, "FY2024/25", "NEWBORN_DEATHS", 0)
    put_raw(session, acholi, "FY2024/25", "DELIVERIES", 100)
    put_raw(session, pader, "FY2024/25", "FRESH_SB", 40)
    put_raw(session, pader, "FY2024/25", "MACERATED_SB", 0)
    put_raw(session, pader, "FY2024/25", "NEWBORN_DEATHS", 0)
    put_raw(session, pader, "FY2024/25", "DELIVERIES", 100)
    put_raw(session, kitgum, "FY2024/25", "FRESH_SB", 10)
    put_raw(session, kitgum, "FY2024/25", "MACERATED_SB", 0)
    put_raw(session, kitgum, "FY2024/25", "NEWBORN_DEATHS", 0)
    put_raw(session, kitgum, "FY2024/25", "DELIVERIES", 100)
    resolved = resolve_source_key(session, acholi, "FY2024/25", "FRESH_SB")
    assert resolved.value == 50
    measure = _eval(session, "PMR", org="ACHOLI")
    assert measure.numerator == 50
    assert measure.denominator == 100
    assert measure.raw_value == 500
    assert measure.raw_value != 100 / 300 * 1000


def test_missing_pmr_component_is_unavailable(session):
    uganda = _unit(session, "UG")
    put_raw(session, uganda, "FY2024/25", "FRESH_SB", 5)
    put_raw(session, uganda, "FY2024/25", "NEWBORN_DEATHS", 4)
    put_raw(session, uganda, "FY2024/25", "DELIVERIES", 1000)
    put_raw(session, uganda, "FY2024/25", "FRESH_SB", 5, programme_code="MPDSR")
    put_raw(session, uganda, "FY2024/25", "NEWBORN_DEATHS", 4, programme_code="MPDSR")
    measure = _eval(session, "PMR")
    assert measure.raw_value is None
    assert "MACERATED_SB" in (measure.missing_components or [])
    reported = _eval(session, "PERINATAL_REPORTED_DEATHS")
    assert reported.raw_value is None


def test_missing_teenage_age_band_is_unavailable(session):
    uganda = _unit(session, "UG")
    put_raw(session, uganda, "FY2024/25", "ANC1_AGE_LT15", 4)
    put_raw(session, uganda, "FY2024/25", "ANC1", 100)
    measure = _eval(session, "TEENAGE_PREGNANCY")
    assert measure.raw_value is None
    assert "ANC1_AGE_15_19" in (measure.missing_components or [])


def test_reported_zero_is_distinct_from_missing_and_not_automatically_unexpected(session):
    uganda = _unit(session, "UG")
    put_raw(session, uganda, "FY2024/25", "ANC1_AGE_LT15", 0)
    put_raw(session, uganda, "FY2024/25", "ANC1_AGE_15_19", 0)
    put_raw(session, uganda, "FY2024/25", "ANC1", 100)
    measure = _eval(session, "TEENAGE_PREGNANCY")
    assert measure.raw_value == 0
    flags = scan_quality(session, org_unit=uganda, period="FY2024/25")
    unexpected = [flag for flag in flags if flag and flag.rule_id == "UNEXPECTED_ZERO"]
    assert unexpected == []
    missing = _eval(session, "HB_TESTING")
    assert missing.numerator is None


def test_direct_child_kmc_percentages_are_not_summed_or_averaged(session):
    pader = _unit(session, "PADER")
    kitgum = _unit(session, "KITGUM")
    acholi = _unit(session, "ACHOLI")
    put_raw(session, pader, "FY2024/25", "KMC_PERCENT", 80)
    put_raw(session, kitgum, "FY2024/25", "KMC_PERCENT", 20)
    measure = _eval(session, "KMC", org="ACHOLI")
    assert measure.raw_value is None
    assert measure.status == "n_a"
    put_raw(session, acholi, "FY2024/25", "KMC_PERCENT", 70)
    direct = _eval(session, "KMC", org="ACHOLI")
    assert direct.raw_value == 70


def test_draft_facility_population_does_not_replace_approved(session):
    hc3 = _unit(session, "PADER_HC_III")
    editor = _user(session, "pader.focal")
    admin = _user(session, "admin.user")
    draft = enter_facility_population(
        session,
        editor,
        org_unit_id=hc3.id,
        year=2024,
        population=1000,
        source_name="TEST_SOURCE",
        population_type="facility_catchment_estimate",
        reason="initial",
    )
    approved = approve_facility_population(session, admin, draft.id, reason="approve")
    second = enter_facility_population(
        session,
        editor,
        org_unit_id=hc3.id,
        year=2024,
        population=9999,
        source_name="TEST_SOURCE_DRAFT",
        population_type="facility_catchment_estimate",
        reason="replacement draft",
    )
    assert second.approval_status == ApprovalStatus.DRAFT.value
    session.refresh(approved)
    assert approved.approval_status == ApprovalStatus.APPROVED.value
    assert approved.is_current_approved is True
    resolved = resolve_population(session, hc3, period_key="FY2024/25")
    assert resolved.population == 1000
    assert resolved.used_facility_entry_id == approved.id


def test_approval_atomically_supersedes_old_population(session):
    hc3 = _unit(session, "PADER_HC_III")
    editor = _user(session, "pader.focal")
    admin = _user(session, "admin.user")
    first = enter_facility_population(
        session,
        editor,
        org_unit_id=hc3.id,
        year=2024,
        population=800,
        source_name="A",
        population_type="facility_catchment_estimate",
        reason="a",
    )
    approve_facility_population(session, admin, first.id, reason="first")
    second = enter_facility_population(
        session,
        editor,
        org_unit_id=hc3.id,
        year=2024,
        population=900,
        source_name="B",
        population_type="facility_catchment_estimate",
        reason="b",
    )
    approve_facility_population(session, admin, second.id, reason="second")
    session.refresh(first)
    session.refresh(second)
    assert first.approval_status == ApprovalStatus.SUPERSEDED.value
    assert first.is_current_approved is False
    assert first.superseded_by_id == second.id
    assert second.is_current_approved is True
    rejected = enter_facility_population(
        session,
        editor,
        org_unit_id=hc3.id,
        year=2024,
        population=100,
        source_name="C",
        population_type="facility_catchment_estimate",
        reason="c",
    )
    reject_facility_population(session, admin, rejected.id, reason="no")
    resolved = resolve_population(session, hc3, period_key="FY2024/25")
    assert resolved.population == 900


def test_facility_population_provenance_identifies_entry(session):
    hc3 = _unit(session, "PADER_HC_III")
    editor = _user(session, "pader.focal")
    admin = _user(session, "admin.user")
    put_population(session, _unit(session, "UG"), 2024, 50000)
    draft = enter_facility_population(
        session,
        editor,
        org_unit_id=hc3.id,
        year=2024,
        population=1200,
        source_name="CATCHMENT",
        population_type="facility_catchment_official",
        reason="use",
    )
    approved = approve_facility_population(session, admin, draft.id, reason="ok")
    put_raw(session, hc3, "FY2024/25", "ANC1", 10)
    run = run_calculation(
        session,
        org_unit=hc3,
        period="FY2024/25",
        user=admin,
        programme_codes=["MNCH"],
        indicator_codes=["ANC1_COVERAGE"],
    )
    value = session.scalar(select(CalculatedValue).where(CalculatedValue.calculation_run_id == run.id))
    assert value.facility_population_entry_id == approved.id
    assert value.population_version_id is None


def test_fy_quarter_uses_configured_population_year(session):
    from tests.helpers import put_period_rule

    assert parse_period("FY2025/26Q3").parent_fy == "FY2025/26"
    assert parse_period("FY2025/26Q3").start == date(2026, 1, 1)
    # Owner decision D-041: a quarter inside a financial year uses that FY base year.
    assert resolve_population_year(session, "FY2025/26Q3") == 2025
    # A financial year with no approved rule still fails closed until one is recorded.
    assert resolve_population_year(session, "FY2032/33Q3") is None
    put_period_rule(session, "FY2032/33", 2032, kinds=["fy", "fy_quarter"])
    assert resolve_population_year(session, "FY2032/33Q3") == 2032
    for key, start, end in (
        ("FY2024/25Q1", date(2024, 7, 1), date(2024, 9, 30)),
        ("FY2024/25Q2", date(2024, 10, 1), date(2024, 12, 31)),
        ("FY2024/25Q3", date(2025, 1, 1), date(2025, 3, 31)),
        ("FY2024/25Q4", date(2025, 4, 1), date(2025, 6, 30)),
        ("FY2025/26Q1", date(2025, 7, 1), date(2025, 9, 30)),
    ):
        spec = parse_period(key)
        assert spec.start == start
        assert spec.end == end


def test_tracker_queries_are_period_bounded():
    seen: dict[str, str] = {}

    from tests.test_dhis2_client import _settings

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.url.params)
        return httpx.Response(200, json={"instances": [], "pager": {"page": 1, "pageCount": 1}})

    client = Dhis2HttpClient(_settings(), transport=httpx.MockTransport(handler))
    TrackerEventsAdapter(client).fetch_events(
        program_uid="TEST_UID_PROGRAM",
        org_unit_uids=["TEST_UID_UG"],
        occurred_after="2024-07-01",
        occurred_before="2024-09-30",
    )
    client.close()
    assert seen["occurredAfter"] == "2024-07-01"
    assert seen["occurredBefore"] == "2024-09-30"


def test_unknown_sync_job_type_returns_422(client, session):
    token = login(client, "admin.user")
    uganda = _unit(session, "UG")
    response = client.post(
        "/sync/jobs",
        json={
            "org_unit_id": str(uganda.id),
            "period": "202407",
            "programme": "MNCH",
            "job_type": "not-a-real-job",
        },
        headers=auth_header(token),
    )
    assert response.status_code == 422


def test_client_program_uid_cannot_bypass_mappings(client, session):
    token = login(client, "admin.user")
    uganda = _unit(session, "UG")
    response = client.post(
        "/sync/jobs",
        json={
            "org_unit_id": str(uganda.id),
            "period": "202407",
            "programme": "MNCH",
            "job_type": "tracker",
            "program_uid": "TEST_UID_ARBITRARY",
        },
        headers=auth_header(token),
    )
    assert response.status_code == 422


def test_mappings_are_programme_version_validity_scoped(session):
    from app.services.mappings import MappingSelectionError, select_aggregate_mappings

    mnch = session.scalar(select(Programme).where(Programme.code == "MNCH"))
    epi = session.scalar(select(Programme).where(Programme.code == "EPI"))
    map_source(session, mnch.id, "ANC1", "TEST_UID_SHARED")
    map_source(session, epi.id, "BCG", "TEST_UID_SHARED")
    mnch_maps = select_aggregate_mappings(session, programme_id=mnch.id, mapping_version="v1")
    epi_maps = select_aggregate_mappings(session, programme_id=epi.id, mapping_version="v1")
    assert {row.internal_source_key for row in mnch_maps} == {"ANC1"}
    assert {row.internal_source_key for row in epi_maps} == {"BCG"}
    session.add(
        SourceMapping(
            internal_source_key="ANC1_DUP",
            programme_id=mnch.id,
            dhis2_item_uid="TEST_UID_SHARED",
            mapping_version="v1",
            enabled=True,
        )
    )
    session.flush()
    try:
        select_aggregate_mappings(session, programme_id=mnch.id, mapping_version="v1")
        raise AssertionError("expected collision")
    except MappingSelectionError:
        pass


def test_nonnumeric_dhis2_value_is_rejected_and_flagged(session):
    payload = {
        "headers": [{"name": "dx"}, {"name": "ou"}, {"name": "pe"}, {"name": "value"}],
        "rows": [["TEST_UID_ANC1", "TEST_UID_UG", "202407", "not-a-number"]],
    }
    rows = parse_analytics_rows(payload)
    assert rows[0].value is None
    assert rows[0].value_invalid is True
    assert rows[0].absence_reason == "invalid_value"
    uganda = _unit(session, "UG")
    programme = session.scalar(select(Programme).where(Programme.code == "MNCH"))
    map_ou(session, uganda, "TEST_UID_UG")
    mapping = map_source(session, programme.id, "ANC1", "TEST_UID_ANC1")
    from app.domain.enums import JobStatus
    from app.models import SyncJob

    job = SyncJob(job_type="aggregate", status=JobStatus.RUNNING.value, mapping_version="v1")
    session.add(job)
    session.flush()
    persist_aggregate_observations(session, job, rows, {"TEST_UID_ANC1": mapping}, datetime.now(UTC))
    stored = session.scalar(select(CalculatedValue).where(False))
    from app.models import RawAggregateValue

    raw = session.scalar(select(RawAggregateValue).where(RawAggregateValue.internal_source_key == "ANC1"))
    assert raw.value_invalid is True
    assert raw.value is None
    assert stored is None


def test_max_pages_does_not_report_complete_success():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(
            200,
            json={
                "instances": [
                    {
                        "event": f"TEST_UID_EV{calls['n']}",
                        "orgUnit": "TEST_UID_UG",
                        "status": "ACTIVE",
                        "dataValues": [],
                    }
                ],
                "pager": {"page": calls["n"], "pageCount": 9},
            },
        )

    from tests.test_dhis2_client import _settings

    settings = _settings(dhis2_max_pages=2, dhis2_page_size=1)
    client = Dhis2HttpClient(settings, transport=httpx.MockTransport(handler))
    result = TrackerEventsAdapter(client).fetch_events_result(
        program_uid="TEST_UID_PROGRAM",
        org_unit_uids=["TEST_UID_UG"],
        occurred_after="2024-07-01",
        occurred_before="2024-07-31",
    )
    client.close()
    assert result.page_limit_reached is True


def test_quality_flags_deduplicate_and_update_lifecycle(session):
    uganda = _unit(session, "UG")
    put_raw(session, uganda, "FY2024/25", "KMC_PERCENT", 110)
    run = run_calculation(session, org_unit=uganda, period="FY2024/25", user=None, indicator_codes=["KMC"])
    first = scan_quality(session, org_unit=uganda, period="FY2024/25", calculation_run=run)
    bounded = [flag for flag in first if flag and flag.rule_id == "BOUNDED_PROPORTION_OVER_100"]
    assert bounded
    first_id = bounded[0].id
    first_seen = bounded[0].first_detected_at
    second = scan_quality(session, org_unit=uganda, period="FY2024/25", calculation_run=run)
    again = [flag for flag in second if flag and flag.rule_id == "BOUNDED_PROPORTION_OVER_100"]
    assert again[0].id == first_id
    assert again[0].last_detected_at >= first_seen
    open_rows = session.scalars(
        select(DataQualityFlag).where(
            DataQualityFlag.rule_id == "BOUNDED_PROPORTION_OVER_100",
            DataQualityFlag.status == QualityStatus.OPEN.value,
        )
    ).all()
    assert len(open_rows) == 1


def test_maternal_timely_boundaries(session):
    uganda = _unit(session, "UG")
    put_raw(session, uganda, "FY2024/25", "MATERNAL_DEATHS", 2, programme_code="MPDSR")
    put_event(
        session,
        uganda,
        status="COMPLETED",
        death_date=date(2024, 8, 1),
        notification_date=date(2024, 8, 1),
        review_date=date(2024, 8, 1),
        data_values={"event_type": "maternal_notification"},
    )
    put_event(
        session,
        uganda,
        status="COMPLETED",
        death_date=date(2024, 8, 1),
        notification_date=date(2024, 8, 2),
        review_date=date(2024, 8, 8),
        data_values={"event_type": "maternal_notification"},
    )
    notify = _eval(session, "MATERNAL_TIMELY_NOTIFICATION")
    assert notify.numerator == 2
    put_event(
        session,
        uganda,
        status="COMPLETED",
        death_date=date(2024, 8, 10),
        review_date=date(2024, 8, 17),
        data_values={"event_type": "maternal_review"},
    )
    put_event(
        session,
        uganda,
        status="COMPLETED",
        death_date=date(2024, 8, 10),
        review_date=date(2024, 8, 18),
        data_values={"event_type": "maternal_review"},
    )
    put_event(
        session,
        uganda,
        status="ACTIVE",
        death_date=date(2024, 8, 10),
        review_date=date(2024, 8, 10),
        data_values={"event_type": "maternal_review"},
    )
    put_event(
        session,
        uganda,
        status="COMPLETED",
        death_date=date(2024, 8, 10),
        review_date=date(2024, 8, 9),
        data_values={"event_type": "maternal_review"},
    )
    review = _eval(session, "MATERNAL_TIMELY_REVIEW")
    assert review.numerator == 1


def test_mv1_mv4_dropout_has_no_invented_thresholds(session):
    uganda = _unit(session, "UG")
    put_raw(session, uganda, "FY2024/25", "MV1", 100)
    put_raw(session, uganda, "FY2024/25", "MV4", 80)
    measure = _eval(session, "MV1_MV4_DROPOUT")
    assert measure.raw_value == 20
    assert measure.status == "n_a"


def test_historical_source_lineage_remains_available(session):
    uganda = _unit(session, "UG")
    put_population(session, uganda, 2024, 10000)
    raw = put_raw(session, uganda, "FY2024/25", "ANC1", 500)
    run = run_calculation(
        session,
        org_unit=uganda,
        period="FY2024/25",
        user=None,
        programme_codes=["MNCH"],
        indicator_codes=["ANC1_COVERAGE"],
    )
    snapshot = run.config_snapshot or {}
    assert snapshot.get("software_version")
    assert snapshot.get("raw_row_ids")
    assert str(raw.id) in snapshot["raw_row_ids"]
    versions = snapshot.get("indicator_versions") or []
    assert any(item["indicator_code"] == "ANC1_COVERAGE" and item.get("formula_spec") for item in versions)
    raw.value = 1
    session.flush()
    stored = session.scalar(select(CalculatedValue).where(CalculatedValue.calculation_run_id == run.id))
    assert stored.source_row_ids
    assert float(stored.raw_value) == 100


def test_disabled_roles_and_expired_scopes_do_not_authorise(session):
    from app.services.authorization import can_access_org_unit, can_access_programme, user_actions

    user = _user(session, "pader.focal")
    role = session.scalar(select(Role).where(Role.code == "district_mch_focal"))
    assert "view" in user_actions(session, user)
    role.is_active = False
    session.flush()
    assert "view" not in user_actions(session, user)
    role.is_active = True
    scope = session.scalar(select(UserGeographyScope).where(UserGeographyScope.user_id == user.id))
    scope.valid_to = date.today() - timedelta(days=1)
    session.flush()
    assert can_access_org_unit(session, user, _unit(session, "PADER")) is False
    prog = session.scalar(select(UserProgrammeScope).where(UserProgrammeScope.user_id == user.id))
    prog.is_active = False
    session.flush()
    assert can_access_programme(session, user, "MNCH") is False


def test_login_does_not_return_or_document_localstorage_token(client):
    response = client.post("/auth/login", json={"username": "national.analyst", "password": "dev-only-change-me"})
    assert response.status_code == 200
    body = response.json()
    assert "access_token" not in body
    assert "hpip_session" in response.cookies
    assert "hpip_csrf" in response.cookies
    from pathlib import Path

    frontend = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "api.ts"
    source = frontend.read_text(encoding="utf-8")
    assert "localStorage" not in source
    assert "hpip_token" not in source
    assert '"http://localhost:8000"' in source
    assert '"http://127.0.0.1:8000"' not in source


def test_csrf_and_logout_revoke_session(client):
    csrf = login(client, "admin.user")
    denied = client.post("/admin/probe")
    assert denied.status_code == 403
    allowed = client.post("/admin/probe", headers=auth_header(csrf))
    assert allowed.status_code == 200
    logout = client.post("/auth/logout", headers=auth_header(csrf))
    assert logout.status_code == 204
    again = client.get("/me/context")
    assert again.status_code == 401


def test_system_admin_lands_at_country(client):
    token = login(client, "admin.user")
    response = client.get("/me/context", headers=auth_header(token))
    assert response.json()["landing_org_unit"]["code"] == "UG"


def test_competing_population_versions_are_deterministic(session):
    uganda = _unit(session, "UG")
    older = PopulationVersion(
        code="POP_OLD",
        name="Older approved",
        source_name="TEST_OLD",
        population_type="projection",
        approval_status=ApprovalStatus.APPROVED.value,
        valid_from=date(2020, 1, 1),
        valid_to=date(2030, 1, 1),
    )
    newer = PopulationVersion(
        code="POP_NEW",
        name="Newer approved",
        source_name="TEST_NEW",
        population_type="projection",
        approval_status=ApprovalStatus.APPROVED.value,
        valid_from=date(2023, 1, 1),
        valid_to=date(2030, 1, 1),
    )
    session.add_all([older, newer])
    session.flush()
    from app.models import PopulationValue

    session.add_all(
        [
            PopulationValue(version_id=older.id, org_unit_id=uganda.id, year=2024, population=1),
            PopulationValue(version_id=newer.id, org_unit_id=uganda.id, year=2024, population=2),
        ]
    )
    session.flush()
    result = resolve_population(session, uganda, period_key="FY2024/25")
    assert result.population == 2
    assert result.version_code == "POP_NEW"


def test_self_approve_is_rejected_for_ordinary_editor(session):
    from app.models import UserPermission
    from app.services.authorization import AuthorizationError

    hc3 = _unit(session, "PADER_HC_III")
    editor = _user(session, "pader.focal")
    session.add(UserPermission(user_id=editor.id, action="approve_population"))
    session.flush()
    draft = enter_facility_population(
        session,
        editor,
        org_unit_id=hc3.id,
        year=2025,
        population=10,
        source_name="X",
        population_type="facility_catchment_estimate",
        reason="x",
    )
    try:
        approve_facility_population(session, editor, draft.id, reason="self")
        raise AssertionError("self-approve should fail")
    except AuthorizationError as exc:
        assert exc.code == "forbidden_action"


def test_caesarean_display_precision_has_no_band_gap(session):
    uganda = _unit(session, "UG")
    put_raw(session, uganda, "FY2024/25", "CS", 4.95)
    put_raw(session, uganda, "FY2024/25", "DELIVERIES", 100)
    assert _eval(session, "CAESAREAN_SECTION").status == "green"
    put_raw(session, uganda, "FY2024/25", "CS", 4.94)
    assert _eval(session, "CAESAREAN_SECTION").status == "yellow"

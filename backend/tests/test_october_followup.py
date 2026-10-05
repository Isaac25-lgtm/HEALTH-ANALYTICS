"""End-to-end follow-up regressions. All source facts and jobs are isolated test fixtures."""

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.models import (
    EventFieldMapping,
    OrgUnit,
    OrgUnitMapping,
    Programme,
    QualityRule,
    RawEventSnapshot,
    SyncJob,
    User,
)
from app.services import facility_data, sync, sync_recovery
from app.services.authorization import require_org_unit_access
from app.services.facility_data import FacilityDataStatus, prefetch_home_district
from app.services.period_rollup import ensure_period_rollups
from app.services.quality import _scan_events
from app.services.sync_reconciliation import reconcile_aggregate_withdrawals, reconcile_event_withdrawals
from tests.conftest import auth_header, login, query_dashboard
from tests.helpers import map_source, put_raw


def _unit(session, code="PADER"):
    return session.scalar(select(OrgUnit).where(OrgUnit.code == code))


def _programme(session, code="MNCH"):
    return session.scalar(select(Programme).where(Programme.code == code))


def _source(session):
    unit = _unit(session)
    programme = _programme(session)
    mapping = map_source(session, programme.id, "ANC1", "TEST_ONLY_FOLLOWUP_ANC1")
    session.add(OrgUnitMapping(org_unit_id=unit.id, source_system="dhis2", external_uid="TEST_ONLY_FOLLOWUP_PADER"))
    session.flush()
    return unit, programme, mapping


def _job(session, unit, programme, *, kind="aggregate", period="202506", status="running"):
    job = SyncJob(
        job_type=kind,
        status=status,
        started_at=datetime.now(UTC) if status in {"running", "succeeded"} else None,
        org_unit_id=unit.id,
        programme_id=programme.id,
        mapping_version="v1",
        period_from=period,
        period_to=period,
    )
    session.add(job)
    session.flush()
    return job


def _raw(session, unit, mapping, *, period="202506", value=100):
    row = put_raw(session, unit, period, "ANC1", value, programme_id=mapping.programme_id)
    # Exercise the DHIS2-only withdrawal boundary; this is still an in-memory fixture.
    row.source_system = "dhis2"
    row.dhis2_item_uid = mapping.dhis2_item_uid
    row.category_option_combo_uid = mapping.category_option_combo_uid or ""
    session.flush()
    return row


def _scope(unit, mapping, period="202506"):
    return dict(
        org_unit_ids=[unit.id],
        source_key="ANC1",
        item_uid=mapping.dhis2_item_uid,
        category_option_combo_uid=mapping.category_option_combo_uid,
        periods=[period],
    )


def test_complete_empty_refresh_withdraws_month_and_rebuilds_year(session, monkeypatch):
    unit, programme, mapping = _source(session)
    months = [f"2024{month:02d}" for month in range(7, 13)] + [f"2025{month:02d}" for month in range(1, 7)]
    monthly = [_raw(session, unit, mapping, period=month, value=10) for month in months]
    ensure_period_rollups(session, ["FY2024/25"])
    from app.models import RawAggregateValue

    old_year = session.scalar(
        select(RawAggregateValue).where(
            RawAggregateValue.org_unit_id == unit.id,
            RawAggregateValue.period == "FY2024/25",
            RawAggregateValue.is_current.is_(True),
        )
    )
    assert float(old_year.value) == 120
    job = _job(session, unit, programme)
    monkeypatch.setattr(sync, "_fetch_aggregate_periods", lambda *_args: ([], 0))
    result = sync._run_aggregate(session, job, unit, ["202506"], SimpleNamespace(last_retry_count=0))
    assert result.status == "succeeded"
    assert not monthly[-1].is_current and monthly[-1].value == 10
    assert monthly[-1].provenance["withdrawal_sync_job_id"] == str(job.id)
    assert job.coverage_manifest["withdrawn_aggregate_count"] == 1
    ensure_period_rollups(session, ["FY2024/25"])
    current = session.scalar(
        select(RawAggregateValue).where(
            RawAggregateValue.org_unit_id == unit.id,
            RawAggregateValue.period == "FY2024/25",
            RawAggregateValue.is_current.is_(True),
        )
    )
    assert current.id != old_year.id and not old_year.is_current
    assert float(current.value) == 110
    assert current.provenance["non_reporting_months"] == ["202506"]
    assert str(job.id) in current.provenance["coverage_job_ids"]


@pytest.mark.parametrize(
    "status,capped,rejected,cancelled",
    [
        ("failed", False, 0, False),
        ("partially_succeeded", False, 0, False),
        ("succeeded", True, 0, False),
        ("succeeded", False, 1, False),
        ("succeeded", False, 0, True),
    ],
)
def test_incomplete_extract_never_withdraws_source(session, status, capped, rejected, cancelled):
    unit, programme, mapping = _source(session)
    row = _raw(session, unit, mapping)
    job = _job(session, unit, programme, status=status)
    job.coverage_manifest = {"complete": True}
    job.page_limit_reached, job.rejected_count, job.cancelled = capped, rejected, cancelled
    assert reconcile_aggregate_withdrawals(session, job, seen_row_ids=set(), scopes=[_scope(unit, mapping)]) == 0
    assert row.is_current and row.value == 100


def test_withdrawal_never_sweeps_other_units_periods_mappings_or_returned_rows(session):
    unit, programme, mapping = _source(session)
    withdrawn = _raw(session, unit, mapping)
    other_unit = _raw(session, _unit(session, "KITGUM"), mapping)
    other_period = _raw(session, unit, mapping, period="202505")
    other_source = put_raw(session, unit, "202506", "ANC4", 88)
    different_coc = _raw(session, unit, mapping, period="202507")
    mapping.category_option_combo_uid = "TEST_ONLY_COC"
    withdrawn.category_option_combo_uid = "TEST_ONLY_COC"
    other_version = _raw(session, unit, mapping, period="202508")
    other_version.mapping_version = "older-version"
    returned = _raw(session, unit, mapping, period="202509")
    job = _job(session, unit, programme, status="succeeded")
    job.coverage_manifest = {"complete": True}
    scope = _scope(unit, mapping)
    scope["periods"] = ["202506", "202507", "202508", "202509"]
    assert reconcile_aggregate_withdrawals(session, job, seen_row_ids={returned.id}, scopes=[scope]) == 1
    assert not withdrawn.is_current
    assert all(
        row.is_current for row in [other_unit, other_period, other_source, different_coc, other_version, returned]
    )


def test_total_request_does_not_withdraw_unrequested_category_or_newer_attempt(session):
    unit, programme, mapping = _source(session)
    older = _raw(session, unit, mapping)
    category = _raw(session, unit, mapping, period="202507")
    category.category_option_combo_uid = "TEST_ONLY_UNREQUESTED_CATEGORY"
    newer = _raw(session, unit, mapping, period="202508")
    job = _job(session, unit, programme, status="succeeded")
    job.started_at = datetime.now(UTC) - timedelta(minutes=5)
    older.extracted_at = job.started_at - timedelta(minutes=1)
    category.extracted_at = older.extracted_at
    job.coverage_manifest = {"complete": True}
    session.flush()
    scope = _scope(unit, mapping)
    scope["periods"] = ["202506", "202507", "202508"]
    assert reconcile_aggregate_withdrawals(session, job, seen_row_ids=set(), scopes=[scope]) == 1
    assert not older.is_current and category.is_current and newer.is_current


def _event(
    session, unit, programme, *, event_uid, age=0, occurred=date(2025, 6, 1), connector="tracker", program_uid=None
):
    row = RawEventSnapshot(
        event_uid=event_uid,
        org_unit_id=unit.id,
        programme_id=programme.id,
        source_connector=connector,
        program_uid=program_uid,
        mapping_version="v1",
        status="ACTIVE",
        occurred_at=datetime.combine(occurred, datetime.min.time(), tzinfo=UTC) if occurred else None,
        death_date=occurred,
        data_values={"event_type": "maternal_death"},
        extracted_at=datetime.now(UTC) - timedelta(hours=age),
        is_current=True,
    )
    session.add(row)
    session.flush()
    return row


def test_quality_ignores_expired_wrong_connector_and_wrong_programme_events(session):
    unit, programme = _unit(session), _programme(session, "MPDSR")
    _event(session, unit, programme, event_uid="TEST_ONLY_EXPIRED", age=30)
    _event(session, unit, programme, event_uid="TEST_ONLY_NOT_TRACKER", connector="event_analytics")
    _event(session, unit, _programme(session), event_uid="TEST_ONLY_WRONG_PROGRAMME")
    valid = _event(session, unit, programme, event_uid="TEST_ONLY_RETAINED")
    rules = {row.code: row for row in session.scalars(select(QualityRule).where(QualityRule.enabled.is_(True)))}
    flags = [flag for flag in _scan_events(session, unit, "202506", None, rules) if flag is not None]
    assert {flag.event_uid for flag in flags} == {valid.event_uid}


def test_quality_retains_missing_death_date_checks_in_dated_closed_facility(session):
    unit, programme = _unit(session, "PADER_HC_III"), _programme(session, "MPDSR")
    unit.active, unit.valid_to = False, date(2025, 7, 31)
    event = _event(session, unit, programme, event_uid="TEST_ONLY_UNDATED")
    event.death_date = None
    session.flush()
    rules = {row.code: row for row in session.scalars(select(QualityRule).where(QualityRule.enabled.is_(True)))}
    flags = [flag for flag in _scan_events(session, _unit(session), "202506", None, rules) if flag is not None]
    assert any(flag.rule_id == "MISSING_CRITICAL_DATE" and flag.event_uid == event.event_uid for flag in flags)
    assert not [flag for flag in _scan_events(session, _unit(session), "202508", None, rules) if flag is not None]


def test_complete_tracker_refresh_withdraws_only_covered_events(session, monkeypatch):
    unit, programme = _unit(session), _programme(session, "MPDSR")
    session.add(OrgUnitMapping(org_unit_id=unit.id, source_system="dhis2", external_uid="TEST_ONLY_FOLLOWUP_PADER"))
    mapping = EventFieldMapping(
        programme_id=programme.id,
        program_uid="TEST_ONLY_FORM",
        mapping_version="v1",
        source_data_element_uid="TEST_ONLY_DATE",
        internal_semantic_field="death_date",
        event_type="maternal_death",
        enabled=True,
    )
    session.add(mapping)
    missing = _event(session, unit, programme, event_uid="TEST_ONLY_MISSING", program_uid=mapping.program_uid)
    outside = _event(
        session,
        unit,
        programme,
        event_uid="TEST_ONLY_OUTSIDE",
        occurred=date(2025, 5, 31),
        program_uid=mapping.program_uid,
    )
    undated = _event(
        session, unit, programme, event_uid="TEST_ONLY_NULL_DATE", occurred=None, program_uid=mapping.program_uid
    )
    another_form = _event(
        session, unit, programme, event_uid="TEST_ONLY_OTHER_FORM", program_uid="TEST_ONLY_UNREQUESTED"
    )
    another_unit = _event(
        session, _unit(session, "KITGUM"), programme, event_uid="TEST_ONLY_OTHER_UNIT", program_uid=mapping.program_uid
    )
    job = _job(session, unit, programme, kind="tracker")
    # Prove a retry of this very same job does not protect its old partial rows.
    missing.sync_job_id = job.id
    session.flush()

    def empty_result(_adapter, **kwargs):
        assert kwargs["ou_mode"] == "DESCENDANTS"
        return sync.TrackerFetchResult(observations=[], page_limit_reached=False, pages_fetched=1)

    monkeypatch.setattr(sync.TrackerEventsAdapter, "fetch_events_result", empty_result)
    result = sync._run_tracker(session, job, unit, ["202506"], SimpleNamespace(last_retry_count=0))
    assert result.status == "succeeded" and result.coverage_manifest["withdrawn_event_count"] == 1
    session.refresh(missing)
    assert not missing.is_current
    assert all(row.is_current for row in [outside, undated, another_form, another_unit])


def test_tracker_withdrawal_batches_keep_returned_rows_and_entire_history(session):
    unit, programme = _unit(session), _programme(session, "MPDSR")
    rows = [
        _event(session, unit, programme, event_uid=f"TEST_ONLY_BATCH_{index}", program_uid="TEST_ONLY_FORM")
        for index in range(503)
    ]
    protected = {rows[0].id, rows[501].id}
    job = _job(session, unit, programme, kind="tracker", status="succeeded")
    job.coverage_manifest = {"complete": True}
    job.window_start, job.window_end = date(2025, 6, 1), date(2025, 6, 30)
    assert (
        reconcile_event_withdrawals(
            session, job, seen_row_ids=protected, root_ids={unit.id}, program_uids={"TEST_ONLY_FORM"}
        )
        == 501
    )
    current_ids = set(session.scalars(select(RawEventSnapshot.id).where(RawEventSnapshot.is_current.is_(True))))
    assert current_ids == protected
    assert session.scalar(select(func.count(RawEventSnapshot.id))) == 503


def test_complete_refresh_keeps_new_returned_fact_and_supersedes_old_fact(session, monkeypatch):
    from app.integrations.dhis2.types import AggregateObservation
    from app.models import RawAggregateValue

    unit, programme, mapping = _source(session)
    previous = _raw(session, unit, mapping, value=10)
    observation = AggregateObservation(
        org_unit_uid="TEST_ONLY_FOLLOWUP_PADER", period="202506", item_uid=mapping.dhis2_item_uid, value=12
    )
    monkeypatch.setattr(sync, "_fetch_aggregate_periods", lambda *_args: ([observation], 1))
    job = _job(session, unit, programme)
    sync._run_aggregate(session, job, unit, ["202506"], SimpleNamespace(last_retry_count=0))
    current = session.scalar(select(RawAggregateValue).where(RawAggregateValue.is_current.is_(True)))
    assert job.status == "succeeded" and job.coverage_manifest["withdrawn_aggregate_count"] == 0
    assert current.value == 12 and current.sync_job_id == job.id
    assert not previous.is_current and previous.superseded_by_id == current.id


def test_partial_tracker_refresh_keeps_previous_evidence(session, monkeypatch):
    unit, programme = _unit(session), _programme(session, "MPDSR")
    row = _event(session, unit, programme, event_uid="TEST_ONLY_PREVIOUS", program_uid="TEST_ONLY_FORM")
    job = _job(session, unit, programme, kind="tracker", status="partially_succeeded")
    job.coverage_manifest = {"complete": False}
    job.window_start, job.window_end = date(2025, 6, 1), date(2025, 6, 30)
    assert (
        reconcile_event_withdrawals(
            session, job, seen_row_ids=set(), root_ids={unit.id}, program_uids={"TEST_ONLY_FORM"}
        )
        == 0
    )
    assert row.is_current


def test_tracker_old_attempt_never_withdraws_newer_extraction(session):
    unit, programme = _unit(session), _programme(session, "MPDSR")
    newer = _event(session, unit, programme, event_uid="TEST_ONLY_NEWER_ATTEMPT", program_uid="TEST_ONLY_FORM")
    job = _job(session, unit, programme, kind="tracker", status="succeeded")
    job.started_at = datetime.now(UTC) - timedelta(minutes=5)
    job.coverage_manifest = {"complete": True}
    job.window_start, job.window_end = date(2025, 6, 1), date(2025, 6, 30)
    assert (
        reconcile_event_withdrawals(
            session, job, seen_row_ids=set(), root_ids={unit.id}, program_uids={"TEST_ONLY_FORM"}
        )
        == 0
    )
    assert newer.is_current


def test_closed_facility_opens_real_historical_dashboard_and_status(client, session):
    unit = _unit(session, "PADER_HC_III")
    unit.active, unit.valid_to = False, date(2025, 7, 31)
    session.commit()
    headers = auth_header(login(client, "admin.user"))
    response = query_dashboard(client, headers, unit.id, period="202506")
    assert response.status_code == 201, response.text
    assert response.json()["scope"]["id"] == str(unit.id)
    status = client.get(
        "/analytics/dashboard/facility-status", params={"org_unit_id": str(unit.id), "period": "202506"}
    )
    assert status.status_code == 200
    after = query_dashboard(client, headers, unit.id, period="202508")
    assert after.status_code == 404


def test_worker_preserves_current_grants_but_accepts_dated_historical_facility(session, monkeypatch):
    unit, programme = _unit(session, "PADER_HC_III"), _programme(session)
    unit.active, unit.valid_to = False, date(2025, 7, 31)
    actor = session.scalar(select(User).where(User.username == "paderhc3.user"))
    require_org_unit_access(session, actor, unit.id, period="202506")
    job = _job(session, unit, programme, kind="aggregate_facilities", status="queued")
    job.initiated_by_user_id = actor.id
    session.flush()
    called = []
    monkeypatch.setattr(sync, "_run_facility_aggregate", lambda *args: called.append(args[2].id) or args[1])
    sync.execute_sync_job(session, job.id, client=SimpleNamespace())
    assert called == [unit.id]
    actor.is_active = False
    job.status = "queued"
    session.flush()
    sync.execute_sync_job(session, job.id, client=SimpleNamespace())
    assert job.status == "failed" and job.error_code == "initiator_permissions_changed"
    assert called == [unit.id]


def test_prefetch_isolates_later_failure_and_returns_earlier_dispatch_ids(session, monkeypatch):
    user = session.scalar(select(User).where(User.username == "pader.focal"))
    monkeypatch.setattr("app.services.authorization.programme_scope_codes", lambda *_args: ["MNCH", "EPI"])
    created = []

    def queue(db, **kwargs):
        job = _job(db, kwargs["org_unit"], _programme(db), status="queued", kind="aggregate_facilities")
        if kwargs["module"] == "immunization":
            raise RuntimeError("TEST_ONLY_programme_failure")
        created.append(str(job.id))
        return FacilityDataStatus("loading", job_id=str(job.id), start_job=True)

    monkeypatch.setattr(facility_data, "queue_facility_load", queue)
    assert prefetch_home_district(session, user) == created
    assert len(created) == 1
    assert session.scalar(select(func.count(SyncJob.id))) == 1


@pytest.fixture()
def recovery_enabled(monkeypatch):
    monkeypatch.setattr(sync_recovery, "get_settings", lambda: SimpleNamespace(dhis2_enabled=True, sync_enabled=True))
    monkeypatch.setattr(sync_recovery, "should_run_eager", lambda: False)


def _old_job(session, *, status="queued", error_code=None, key=None):
    row = _job(session, _unit(session), _programme(session), kind="aggregate_facilities", status=status)
    row.updated_at = datetime.now(UTC) - timedelta(minutes=5)
    row.error_code, row.idempotency_key = error_code, key
    session.commit()
    return row


def test_recover_committed_unpublished_job_and_throttle_duplicate_delivery(session, recovery_enabled):
    row = _old_job(session)
    deliveries = []
    now = datetime.now(UTC)
    result = sync_recovery.recover_sync_dispatch(session, now=now, dispatch=deliveries.append)
    assert result["published"] == 1 and deliveries == [row.id]
    assert sync_recovery.recover_sync_dispatch(session, now=now, dispatch=deliveries.append)["published"] == 0
    # Broker publication is not proof of execution; a missing worker/ack is safely
    # redelivered until the worker's durable claim changes queued -> running.
    assert (
        sync_recovery.recover_sync_dispatch(session, now=now + timedelta(minutes=2), dispatch=deliveries.append)[
            "published"
        ]
        == 1
    )
    row.status = "running"
    row.started_at = now
    session.commit()
    assert (
        sync_recovery.recover_sync_dispatch(session, now=now + timedelta(minutes=5), dispatch=deliveries.append)[
            "published"
        ]
        == 0
    )


def test_recovery_records_broker_failure_then_retries_without_losing_job(session, recovery_enabled):
    row = _old_job(session)
    now = datetime.now(UTC)

    def down(_job_id):
        raise sync.SyncDispatchError("TEST_ONLY_queue_unavailable")

    assert sync_recovery.recover_sync_dispatch(session, now=now, dispatch=down)["publication_failed"] == 1
    session.refresh(row)
    assert row.status == "queued" and row.error_code == "sync_enqueue_failed"
    deliveries = []
    assert (
        sync_recovery.recover_sync_dispatch(session, now=now + timedelta(minutes=2), dispatch=deliveries.append)[
            "published"
        ]
        == 1
    )
    assert deliveries == [row.id]


def test_recovery_retries_only_publication_failures_and_never_cancellation_or_extraction_failure(
    session, recovery_enabled
):
    recoverable = _old_job(session, status="failed", error_code="sync_enqueue_failed")
    failed = _old_job(session, status="failed", error_code="mapping_missing")
    cancelled = _old_job(session)
    cancelled.cancelled = True
    ran = _old_job(session, status="failed", error_code="sync_enqueue_failed")
    ran.started_at = datetime.now(UTC) - timedelta(minutes=2)
    session.commit()
    deliveries = []
    assert sync_recovery.recover_sync_dispatch(session, dispatch=deliveries.append)["published"] == 1
    assert deliveries == [recoverable.id]
    assert failed.status == "failed" and cancelled.cancelled and ran.status == "failed"


def test_recovery_does_not_reactivate_replaced_active_facility_key(session, recovery_enabled):
    previous = _old_job(session, status="failed", error_code="facility_load_failed", key="TEST_ONLY_SHARED")
    newer = _old_job(session, key=previous.idempotency_key)
    deliveries = []
    result = sync_recovery.recover_sync_dispatch(session, dispatch=deliveries.append)
    assert result["published"] == 1 and deliveries == [newer.id]
    assert previous.status == "failed"


def test_recovery_never_publishes_when_runtime_extraction_is_disabled(session, monkeypatch):
    _old_job(session)
    monkeypatch.setattr(sync_recovery, "get_settings", lambda: SimpleNamespace(dhis2_enabled=False, sync_enabled=True))
    deliveries = []
    assert sync_recovery.recover_sync_dispatch(session, dispatch=deliveries.append)["disabled"]
    assert deliveries == []


def test_recovery_cli_starts_in_fresh_process_and_disabled_mode_needs_no_schema():
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path

    env = {
        **os.environ,
        "APP_ENV": "test",
        "DATABASE_URL": "sqlite+pysqlite:///:memory:",
        "DHIS2_ENABLED": "false",
        "SYNC_ENABLED": "false",
        "DHIS2_LOGIN_ENABLED": "false",
        "DHIS2_BASE_URL": "",
        "DHIS2_USERNAME": "",
        "DHIS2_PASSWORD": "",
        "DHIS2_PAT": "",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    result = subprocess.run(
        [sys.executable, "-m", "scripts.recover_sync_dispatch", "--limit", "100"],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert json.loads(result.stdout) == {"disabled": True, "published": 0, "publication_failed": 0, "skipped": 0}


def test_tracker_datetime_boundaries_preserve_explicit_time_and_expand_date_only():
    from app.integrations.dhis2.tracker import _occurred_bound

    assert _occurred_bound("2025-06-01") == "2025-06-01T00:00:00.000"
    assert _occurred_bound("2025-06-30", end=True) == "2025-06-30T23:59:59.999"
    explicit = "2025-06-30T10:15:23+03:00"
    assert _occurred_bound(explicit) == explicit and _occurred_bound(explicit, end=True) == explicit


def test_failed_publication_remains_pollable_without_queuing_a_replacement(session):
    map_source(session, _programme(session).id, "ANC1", "TEST_ONLY_RETRY_ANC1")
    row = _old_job(session, status="failed", error_code="facility_load_failed")
    status = facility_data.facility_data_status(session, org_unit=_unit(session), period="202506", module="anc")
    assert status.status == "loading" and status.job_id == str(row.id)
    assert not status.start_job and "recovery" in status.message


def test_exact_manifest_does_not_certify_unrequested_parent_counts(session):
    from app.services.period_rollup import _missing_month_coverage

    parent, child = _unit(session, "ACHOLI"), _unit(session)
    job = _job(session, parent, _programme(session), status="succeeded")
    job.coverage_manifest = {
        "complete": True,
        "org_unit_ids": [str(parent.id), str(child.id)],
        "source_keys": ["ANC1", "KMC_PERCENT"],
        "periods": ["202506"],
        "requests": [
            {"source_key": "ANC1", "org_unit_ids": [str(child.id)], "periods": ["202506"]},
            {"source_key": "KMC_PERCENT", "org_unit_ids": [str(parent.id)], "periods": ["202506"]},
        ],
    }
    assert _missing_month_coverage([job], job.programme_id, parent.id, "ANC1", "v1", {"202506"}) is None
    assert _missing_month_coverage([job], job.programme_id, child.id, "ANC1", "v1", {"202506"}) == [job]


def test_publication_failure_cannot_overwrite_a_worker_claim(session, monkeypatch):
    from fastapi import HTTPException

    from app.api.routes import sync as routes

    job = _job(session, _unit(session), _programme(session), status="queued")
    monkeypatch.setattr(routes, "should_run_eager", lambda: False)

    def uncertain(_job_id):
        job.status = "running"
        job.started_at = datetime.now(UTC)
        session.commit()
        raise sync.SyncDispatchError("TEST_ONLY_broker_ack_lost")

    monkeypatch.setattr(routes, "dispatch_sync_job", uncertain)
    with pytest.raises(HTTPException) as caught:
        routes._dispatch_created_job(session, job)
    assert caught.value.status_code == 503
    session.refresh(job)
    assert job.status == "running" and job.finished_at is None and job.error_code is None


def test_recovery_schedule_uses_existing_maintenance_queue_only_when_sync_is_enabled(monkeypatch):
    from app.config import Settings
    from app.workers import celery_app as worker

    enabled = Settings(_env_file=None, app_env="test", dhis2_enabled=True, sync_enabled=True, sync_execution="queue")
    monkeypatch.setattr(worker, "get_settings", lambda: enabled)
    config = worker.celery_config()
    schedule = config["beat_schedule"]["hpip-recover-sync-dispatch"]
    assert schedule["task"] == worker.RECOVER_SYNC_TASK_NAME and schedule["schedule"] == 60.0
    assert schedule["options"]["queue"] == enabled.maintenance_queue_name
    enabled.sync_enabled = False
    assert "hpip-recover-sync-dispatch" not in worker.celery_config()["beat_schedule"]

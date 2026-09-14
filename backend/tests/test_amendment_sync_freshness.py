"""Amendment §12: freshness is written after final status, finish time and duration, deterministically."""

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select

from app.integrations.dhis2.http import Dhis2HttpClient
from app.models import EventFieldMapping, FreshnessSnapshot, OrgUnit, Programme, SyncJob
from app.services.event_coverage import evaluate_event_coverage
from app.services.sync import _oldest_freshness, _record_freshness, enqueue_sync_job, execute_sync_job
from tests.conftest import auth_header, login
from tests.helpers import TEST_MPDSR_PROGRAM_UID, map_ou, map_source
from tests.test_dhis2_client import _settings


def _unit(session, code):
    return session.scalar(select(OrgUnit).where(OrgUnit.code == code))


def _programme(session, code):
    return session.scalar(select(Programme).where(Programme.code == code))


def _aware(value):
    return value if value is None or value.tzinfo else value.replace(tzinfo=UTC)


def _freshness(session, connector):
    return session.scalar(select(FreshnessSnapshot).where(FreshnessSnapshot.connector == connector))


def _analytics_client(server_date: str | None = None, *, fail: bool = False) -> Dhis2HttpClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if fail:
            return httpx.Response(500, json={"message": "synthetic failure"})
        return httpx.Response(
            200,
            json={
                "headers": [{"name": "dx"}, {"name": "ou"}, {"name": "pe"}, {"name": "value"}],
                "rows": [["TEST_UID_ANC1", "TEST_UID_UG", "202407", "12"]],
                "serverDate": server_date,
            },
        )

    return Dhis2HttpClient(_settings(), transport=httpx.MockTransport(handler))


def test_successful_sync_records_freshness_after_finish_and_failures_keep_last_success(session):
    uganda = _unit(session, "UG")
    mnch = _programme(session, "MNCH")
    map_ou(session, uganda, "TEST_UID_UG")
    map_source(session, mnch.id, "ANC1", "TEST_UID_ANC1")
    job = enqueue_sync_job(
        session, org_unit=uganda, periods=["202407"], user=None, job_type="aggregate", programme_id=mnch.id
    )
    execute_sync_job(session, job.id, client=_analytics_client("2024-08-01T06:00:00Z"))
    assert job.status == "succeeded"
    assert job.finished_at is not None and job.duration_ms is not None
    row = _freshness(session, "aggregate")
    assert row.status == "succeeded"
    assert row.sync_job_id == job.id
    assert _aware(row.last_success_at) == _aware(job.finished_at)
    assert _aware(row.source_freshness_at) == datetime(2024, 8, 1, 6, tzinfo=UTC)
    assert row.lag_seconds == int((_aware(job.finished_at) - datetime(2024, 8, 1, 6, tzinfo=UTC)).total_seconds())
    assert row.detail["last_attempt"]["sync_job_id"] == str(job.id)

    failing = enqueue_sync_job(
        session, org_unit=uganda, periods=["202407"], user=None, job_type="aggregate", programme_id=mnch.id
    )
    execute_sync_job(session, failing.id, client=_analytics_client(fail=True))
    assert failing.status == "failed"
    session.refresh(row)
    assert row.status == "failed"
    assert row.sync_job_id == job.id
    assert _aware(row.last_success_at) == _aware(job.finished_at)
    assert row.detail["last_attempt"] == {
        "sync_job_id": str(failing.id),
        "status": "failed",
        "finished_at": _aware(failing.finished_at).isoformat(),
        "error_code": failing.error_code,
    }


def test_source_freshness_is_the_oldest_reported_value():
    newest = datetime(2024, 8, 3, tzinfo=UTC)
    oldest = datetime(2024, 8, 1)
    middle = datetime(2024, 8, 2, tzinfo=UTC)
    items = [SimpleNamespace(source_freshness_at=value) for value in (newest, None, oldest, middle)]
    assert _oldest_freshness(items) == oldest.replace(tzinfo=UTC)
    assert _oldest_freshness(list(reversed(items))) == oldest.replace(tzinfo=UTC)
    assert _oldest_freshness([SimpleNamespace(source_freshness_at=None)]) is None


def test_freshness_cannot_be_recorded_before_the_job_finishes(session):
    job = SyncJob(job_type="aggregate", status="running")
    session.add(job)
    session.flush()
    with pytest.raises(ValueError):
        _record_freshness(session, "aggregate", job)
    assert _freshness(session, "aggregate") is None


def _tracker_setup(session):
    acholi = _unit(session, "ACHOLI")
    mpdsr = _programme(session, "MPDSR")
    map_ou(session, acholi, "TEST_UID_ACHOLI")
    session.add(
        EventFieldMapping(
            programme_id=mpdsr.id,
            program_uid=TEST_MPDSR_PROGRAM_UID,
            source_data_element_uid="TEST_UID_DE_DEATH_DATE",
            internal_semantic_field="death_date",
            event_type="maternal_notification",
            mapping_version="v1",
            enabled=True,
        )
    )
    session.flush()
    return acholi, mpdsr


def _tracker_client(seen: dict) -> Dhis2HttpClient:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.url.params)
        return httpx.Response(200, json={"instances": [], "pager": {"page": 1, "pageCount": 1}})

    return Dhis2HttpClient(_settings(), transport=httpx.MockTransport(handler))


def test_tracker_window_through_extraction_date_verifies_an_empty_cohort(session):
    acholi, mpdsr = _tracker_setup(session)
    today = datetime.now(UTC).date()
    seen: dict = {}
    job = enqueue_sync_job(
        session,
        org_unit=acholi,
        periods=["FY2024/25"],
        user=None,
        job_type="tracker",
        programme_id=mpdsr.id,
        window_end=today,
    )
    execute_sync_job(session, job.id, client=_tracker_client(seen))
    assert job.status == "succeeded"
    assert (job.window_start, job.window_end) == (date(2024, 7, 1), today)
    assert (seen["occurredAfter"], seen["occurredBefore"]) == ("2024-07-01", today.isoformat())
    tracker = _freshness(session, "tracker")
    assert _aware(tracker.source_freshness_at) == _aware(job.finished_at)
    coverage = evaluate_event_coverage(session, org_unit=acholi, period="FY2024/25", required_end=None)
    assert coverage["status"] == "verified"
    assert coverage["sync_job_id"] == str(job.id)


def test_period_only_tracker_window_does_not_verify_follow_up(session):
    acholi, mpdsr = _tracker_setup(session)
    seen: dict = {}
    job = enqueue_sync_job(
        session, org_unit=acholi, periods=["FY2024/25"], user=None, job_type="tracker", programme_id=mpdsr.id
    )
    execute_sync_job(session, job.id, client=_tracker_client(seen))
    assert job.status == "succeeded"
    assert job.window_end == date(2025, 6, 30)
    review = evaluate_event_coverage(
        session, org_unit=acholi, period="FY2024/25", required_end=date(2025, 6, 30) + timedelta(days=7)
    )
    assert review["status"] == "unverified"
    assert review["coverage_failure"] == "window"


@pytest.mark.parametrize(
    ("job_type", "window_end", "code"),
    [
        ("aggregate", "2025-07-10", "event_window_not_supported"),
        ("tracker", "2025-06-29", "invalid_event_window"),
        ("tracker", (datetime.now(UTC).date() + timedelta(days=2)).isoformat(), "invalid_event_window"),
    ],
)
def test_event_window_end_is_validated(client, session, job_type, window_end, code):
    token = login(client, "admin.user")
    response = client.post(
        "/sync/jobs",
        json={
            "org_unit_id": str(_unit(session, "UG").id),
            "period": "FY2024/25",
            "programme": "MPDSR",
            "job_type": job_type,
            "event_window_end": window_end,
        },
        headers=auth_header(token),
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == code
    assert session.scalars(select(SyncJob)).all() == []


def test_freshness_endpoint_reports_last_success_and_last_attempt(client, session):
    uganda = _unit(session, "UG")
    mnch = _programme(session, "MNCH")
    map_ou(session, uganda, "TEST_UID_UG")
    map_source(session, mnch.id, "ANC1", "TEST_UID_ANC1")
    job = enqueue_sync_job(
        session, org_unit=uganda, periods=["202407"], user=None, job_type="aggregate", programme_id=mnch.id
    )
    execute_sync_job(session, job.id, client=_analytics_client("2024-08-01T06:00:00Z"))
    session.commit()
    token = login(client, "national.analyst")
    rows = {row["connector"]: row for row in client.get("/sync/freshness", headers=auth_header(token)).json()}
    assert rows["aggregate"]["last_success_sync_job_id"] == str(job.id)
    assert rows["aggregate"]["last_attempt"]["status"] == "succeeded"

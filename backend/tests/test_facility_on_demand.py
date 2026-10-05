"""D-068: facility figures load on demand for one district, and only what is missing."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.domain.enums import JobStatus, MappingSourceSystem
from app.models import OrgUnit, OrgUnitMapping, Programme, SourceMapping, SyncJob, User
from app.services import facility_data, sync
from app.services.facility_data import (
    FACILITY_JOB_TYPE,
    facility_data_status,
    prefetch_home_district,
    queue_facility_load,
)
from tests.helpers import map_source

NOW = datetime(2026, 9, 25, 10, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def approved_test_mapping(session):
    programme = session.scalar(select(Programme).where(Programme.code == "MNCH"))
    map_source(session, programme.id, "ANC1", "TEST_ONLY_FACILITY_ANC1")


def _unit(session, code):
    return session.scalar(select(OrgUnit).where(OrgUnit.code == code))


@pytest.fixture()
def extraction_on(monkeypatch):
    monkeypatch.setattr(facility_data, "ensure_extraction_enabled", lambda _settings: None)


def _job(session, district, months, status=JobStatus.SUCCEEDED.value, finished=NOW):
    programme = session.scalar(select(Programme).where(Programme.code == "MNCH"))
    job = SyncJob(
        id=uuid4(),
        job_type=FACILITY_JOB_TYPE,
        status=status,
        org_unit_id=district.id,
        programme_id=programme.id,
        period_from=months[0],
        period_to=months[-1],
        finished_at=finished,
        mapping_version="v1",
        coverage_manifest={
            "complete": status == JobStatus.SUCCEEDED.value,
            "periods": facility_data._month_keys(months[0], months[-1]),
            "mapping_ids": [str(row.id) for row in session.scalars(select(SourceMapping))],
            "org_unit_ids": [
                str(unit.id)
                for unit in session.scalars(select(OrgUnit)).all()
                if unit.level_type == "facility" and unit.path.startswith(district.path.rstrip("/") + "/")
            ],
        },
    )
    session.add(job)
    session.flush()
    return job


def test_missing_months_need_a_load_and_loaded_months_are_ready(session):
    pader = _unit(session, "PADER")
    status = facility_data_status(session, org_unit=pader, period="FY2024/25", module="anc", now=NOW)
    assert status.start_job and status.months_requested == 12
    assert status.missing == [f"2024{m:02d}" for m in range(7, 13)] + [f"2025{m:02d}" for m in range(1, 7)]
    _job(session, pader, status.missing)
    ready = facility_data_status(session, org_unit=pader, period="FY2024/25", module="anc", now=NOW)
    assert ready.status == "ready" and ready.months_loaded == 12 and not ready.start_job


def test_facility_screen_resolves_its_district(session):
    facility = _unit(session, "PADER_HC_III")
    status = facility_data_status(session, org_unit=facility, period="202506", module="anc", now=NOW)
    assert status.district_id == _unit(session, "PADER").id


def test_recent_months_are_rechecked_after_a_day(session):
    pader = _unit(session, "PADER")
    _job(session, pader, ["202607", "202608"], finished=NOW - timedelta(hours=30))
    status = facility_data_status(session, org_unit=pader, period="202607..202608", module="anc", now=NOW)
    assert status.start_job and status.missing == ["202607", "202608"]
    _job(session, pader, ["202607", "202608"], finished=NOW - timedelta(hours=2))
    assert (
        facility_data_status(session, org_unit=pader, period="202607..202608", module="anc", now=NOW).status == "ready"
    )


def test_a_running_load_is_reused_not_duplicated(session, extraction_on):
    pader = _unit(session, "PADER")
    first = queue_facility_load(session, user=None, org_unit=pader, period="FY2024/25", module="anc")
    session.flush()
    second = queue_facility_load(session, user=None, org_unit=pader, period="FY2024/25", module="anc")
    assert first.start_job and not second.start_job
    assert second.status == "loading" and second.job_id == first.job_id


def test_nothing_is_queued_when_dhis2_extraction_is_off(session):
    pader = _unit(session, "PADER")
    status = queue_facility_load(session, user=None, org_unit=pader, period="FY2024/25", module="anc")
    assert status.status == "unavailable" and status.job_id is None
    assert session.scalar(select(func.count()).where(SyncJob.job_type == FACILITY_JOB_TYPE)) == 0


def test_facility_job_fetches_the_district_facilities_for_every_month(session, monkeypatch):
    pader = _unit(session, "PADER")
    facility = _unit(session, "PADER_HC_III")
    session.add(
        OrgUnitMapping(org_unit_id=facility.id, source_system=MappingSourceSystem.DHIS2.value, external_uid="FAC_UID")
    )
    job = _job(session, pader, ["202505", "202507"], status=JobStatus.RUNNING.value, finished=None)
    captured = {}

    def fake_aggregate(_session, _job, org_unit, periods, _client, org_unit_uids=None):
        captured.update(org_unit=org_unit, periods=periods, uids=org_unit_uids)
        return _job

    monkeypatch.setattr(sync, "_run_aggregate", fake_aggregate)
    sync._run_facility_aggregate(session, job, pader, None)
    assert captured == {"org_unit": pader, "periods": ["202505", "202506", "202507"], "uids": ["FAC_UID"]}


def test_district_user_sign_in_queues_the_home_district(session, extraction_on):
    focal = session.scalar(select(User).where(User.username == "pader.focal"))
    jobs = prefetch_home_district(session, focal)
    assert len(jobs) == 1  # MNCH only: the focal person's one programme
    job = session.get(SyncJob, UUID(jobs[0]))
    assert job.job_type == FACILITY_JOB_TYPE and job.org_unit_id == _unit(session, "PADER").id
    national = session.scalar(select(User).where(User.username == "national.analyst"))
    assert prefetch_home_district(session, national) == []

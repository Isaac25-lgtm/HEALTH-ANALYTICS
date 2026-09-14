from datetime import UTC, datetime

from sqlalchemy import select

from app.models import OrgUnit, Programme, RawAggregateValue
from app.services.sync import persist_aggregate_observations, run_aggregate_sync
from tests.helpers import map_ou, map_source


def test_mapping_failure_and_persist(session):
    uganda = session.scalar(select(OrgUnit).where(OrgUnit.code == "UG"))
    programme = session.scalar(select(Programme).where(Programme.code == "MNCH"))
    map_ou(session, uganda, "TEST_UID_UG")
    mapping = map_source(session, programme.id, "ANC1", "TEST_UID_ANC1")
    from app.domain.enums import JobStatus
    from app.integrations.dhis2.types import AggregateObservation
    from app.models import SyncJob

    job = SyncJob(job_type="aggregate", status=JobStatus.RUNNING.value, mapping_version="v1")
    session.add(job)
    session.flush()
    observations = [
        AggregateObservation(
            org_unit_uid="TEST_UID_UG",
            period="202407",
            item_uid="TEST_UID_ANC1",
            value=9,
            payload_checksum="abc",
        ),
        AggregateObservation(
            org_unit_uid="TEST_UID_UNKNOWN",
            period="202407",
            item_uid="TEST_UID_ANC1",
            value=1,
        ),
    ]
    counts = persist_aggregate_observations(
        session, job, observations, {"TEST_UID_ANC1": mapping}, datetime.now(UTC)
    )
    assert counts["stored"] == 1
    assert counts["rejected"] >= 1
    stored = session.scalar(select(RawAggregateValue).where(RawAggregateValue.internal_source_key == "ANC1"))
    assert stored.value == 9
    assert stored.dhis2_item_uid.startswith("TEST_UID_")


def test_sync_job_without_live_dhis2(session):
    uganda = session.scalar(select(OrgUnit).where(OrgUnit.code == "UG"))
    job = run_aggregate_sync(session, org_unit=uganda, periods=["202407"], user=None)
    assert job.status in {"failed", "succeeded", "partially_succeeded"}
    assert job.error_code in {None, "dhis2_not_configured", "mapping_missing"}

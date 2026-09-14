"""MPDSR data minimisation (work package E).

Ingestion stores an explicit whitelist of approved semantic fields and nothing else. Identifying
fields, nested payloads and narratives never reach the database, dashboards, AI evidence, exports
or operational logs, and event UIDs live only in the 24-hour event cache.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.domain.mpdsr_minimisation import (
    APPROVED_EVENT_SEMANTIC_FIELDS,
    DROP_NESTED,
    DROP_NOT_APPROVED,
    DROP_TOO_LONG,
    MAX_VALUE_LENGTH,
    minimise_event_values,
)
from app.integrations.dhis2.types import EventObservation
from app.models import EventFieldMapping, OrgUnit, OrgUnitMapping, Programme, RawEventSnapshot, SyncJob
from app.services.evidence import evidence_package
from app.services.observability import clear_operational_events, recent_operational_events
from app.services.sync import persist_event_observations
from tests.conftest import auth_header, login, query_dashboard
from tests.helpers import put_event, put_population, put_raw

IDENTIFYING = {
    "patient_name": "Jane Doe",
    "mother_name": "Mary Doe",
    "clinician": "Dr Smith",
    "reviewer_name": "Dr Jones",
    "phone": "+256700000000",
    "address": "Plot 4, Kitgum",
    "narrative": "The mother arrived at 02:00 after a long journey and was seen by the midwife.",
    "national_id": "CM123456789",
    "tracked_entity_instance": "abc123XYZ99",
}


def _unit(session, code="PADER"):
    return session.scalar(select(OrgUnit).where(OrgUnit.code == code))


# ---------------------------------------------------------------------------
# The whitelist itself
# ---------------------------------------------------------------------------


def test_only_approved_fields_survive_minimisation():
    result = minimise_event_values({**IDENTIFYING, "death_date": "2025-01-04", "event_type": "maternal_death"})
    assert result.values == {"death_date": "2025-01-04", "event_type": "maternal_death"}
    assert set(result.dropped) == set(IDENTIFYING)
    assert set(result.dropped.values()) == {DROP_NOT_APPROVED}


def test_unexpected_and_nested_payloads_are_refused():
    result = minimise_event_values(
        {
            "death_date": "2025-01-04",
            "cause_mentions": ["haemorrhage", {"patient": "Jane"}],
            "event_type": {"nested": {"patient_name": "Jane"}},
            "surprise_attribute": "anything",
        }
    )
    assert result.values["death_date"] == "2025-01-04"
    assert result.values["cause_mentions"] == ["haemorrhage"]
    assert "event_type" not in result.values
    assert result.dropped["event_type"] == DROP_NESTED
    assert result.dropped["surprise_attribute"] == DROP_NOT_APPROVED
    assert json.dumps(result.values).find("Jane") == -1


def test_narratives_cannot_hide_inside_an_approved_field():
    narrative = "x" * (MAX_VALUE_LENGTH + 1)
    result = minimise_event_values({"cause_mentions": narrative, "death_date": "2025-01-04"})
    assert "cause_mentions" not in result.values
    assert result.dropped["cause_mentions"] == DROP_TOO_LONG
    assert result.values == {"death_date": "2025-01-04"}


def test_whitelist_stays_minimal_and_excludes_identity():
    assert APPROVED_EVENT_SEMANTIC_FIELDS == {
        "event_type",
        "death_date",
        "notification_date",
        "review_date",
        "cause_mentions",
        "structured_cause_mentions",
    }
    for forbidden in IDENTIFYING:
        assert forbidden not in APPROVED_EVENT_SEMANTIC_FIELDS


# ---------------------------------------------------------------------------
# The real ingestion path
# ---------------------------------------------------------------------------


@pytest.fixture()
def tracker_job(session):
    programme = session.scalar(select(Programme).where(Programme.code == "MPDSR"))
    facility = _unit(session, "PADER_HC_III")
    session.add(
        OrgUnitMapping(
            org_unit_id=facility.id,
            external_uid="TEST_UID_OU_FACILITY",
            source_system="dhis2",
            valid_from=date(2020, 1, 1),
        )
    )
    mappings = []
    for field_name, uid in (
        ("death_date", "TEST_UID_DE_DEATH_DATE"),
        ("notification_date", "TEST_UID_DE_NOTIFY"),
        # A misconfigured mapping that points at an identifying element must still be refused.
        ("patient_name", "TEST_UID_DE_NAME"),
        ("narrative", "TEST_UID_DE_NARRATIVE"),
    ):
        mapping = EventFieldMapping(
            programme_id=programme.id,
            program_uid="TEST_UID_MPDSR_PROGRAM",
            source_data_element_uid=uid,
            internal_semantic_field=field_name,
            event_type="maternal_death",
            mapping_version="v1",
            enabled=True,
        )
        mappings.append(mapping)
        session.add(mapping)
    job = SyncJob(
        id=uuid4(),
        job_type="tracker",
        status="running",
        programme_id=programme.id,
        mapping_version="v1",
        period_from="FY2024/25",
        period_to="FY2024/25",
    )
    session.add(job)
    session.commit()
    return job, mappings


def _observation(**values) -> EventObservation:
    return EventObservation(
        event_uid="TEST_UID_EVENT_MIN1",
        source_connector="tracker",
        program_uid="TEST_UID_MPDSR_PROGRAM",
        program_stage_uid=None,
        org_unit_uid="TEST_UID_OU_FACILITY",
        status="COMPLETED",
        occurred_at=datetime(2025, 1, 4, tzinfo=UTC),
        completed_at=datetime(2025, 1, 6, tzinfo=UTC),
        source_created_at=None,
        source_updated_at=None,
        data_values=values,
    )


def test_ingestion_persists_only_approved_fields(session, tracker_job):
    job, mappings = tracker_job
    clear_operational_events()
    observation = _observation(
        TEST_UID_DE_DEATH_DATE="2025-01-04",
        TEST_UID_DE_NOTIFY="2025-01-05",
        TEST_UID_DE_NAME="Jane Doe",
        TEST_UID_DE_NARRATIVE="Long clinical narrative about the mother and her family.",
        TEST_UID_DE_UNMAPPED="unmapped value",
    )
    outcome = persist_event_observations(session, job, [observation], mappings, datetime.now(UTC))
    session.commit()
    assert outcome["stored"] == 1
    assert outcome["dropped_fields"] >= 2
    row = session.scalar(select(RawEventSnapshot))
    assert set(row.data_values) <= APPROVED_EVENT_SEMANTIC_FIELDS
    assert row.data_values["death_date"] == "2025-01-04"
    assert row.death_date == date(2025, 1, 4)
    assert row.notification_date == date(2025, 1, 5)
    encoded = json.dumps(row.data_values)
    for leaked in ("Jane", "Doe", "narrative", "Long clinical", "unmapped value"):
        assert leaked not in encoded
    # Operational visibility records a count, never the field names or values.
    events = [item for item in recent_operational_events() if item["event_type"] == "mpdsr_event_fields_dropped"]
    assert events and events[0]["records_rejected"] >= 2
    assert "Jane" not in json.dumps(events)


def test_event_uid_is_the_only_identifier_and_never_leaves_the_cache(client, session):
    org = _unit(session)
    put_population(session, org, 2024, 1_000_000, code="MIN_POP")
    put_raw(session, org, "FY2024/25", "ANC1", 1_000)
    put_event(
        session,
        org,
        event_uid="TEST_UID_EVENT_SECRET",
        death_date=date(2024, 8, 1),
        notification_date=date(2024, 8, 2),
        review_date=date(2024, 8, 5),
        data_values={"event_type": "maternal_death", "cause_mentions": ["haemorrhage"]},
    )
    session.commit()
    headers = auth_header(login(client, "admin.user"))
    dashboard = query_dashboard(client, headers, org.id, module="mpdsr")
    assert dashboard.status_code == 201, dashboard.text
    payload = dashboard.json()
    encoded = json.dumps(payload)
    assert "TEST_UID_EVENT_SECRET" not in encoded

    # AI evidence is built from the same snapshot and must stay free of identifiers.
    package = evidence_package(payload)
    assert "TEST_UID_EVENT_SECRET" not in json.dumps(package)
    assert "event_uid" not in json.dumps(package)

    # The module payload reports counts and coverage, not case rows.
    module = payload["module_result"]
    assert module["module"] == "mpdsr"
    assert "events" not in module


def test_mpdsr_line_list_export_stays_blocked(client, session):
    org = _unit(session)
    headers = auth_header(login(client, "admin.user"))
    response = client.post(f"/exports/mpdsr-linelist?org_unit_id={org.id}", headers=headers)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "mpdsr_linelist_blocked"


def test_cause_analysis_and_timeliness_stay_disabled_without_approved_governance(client, session):
    org = session.scalar(select(OrgUnit).where(OrgUnit.code == "UG"))
    assert get_settings().mpdsr_cause_min_cell_count is None
    headers = auth_header(login(client, "admin.user"))
    payload = query_dashboard(client, headers, org.id, module="mpdsr").json()
    mpdsr = payload["module_result"]["mpdsr"]
    assert mpdsr["cause_disclosure"]["status"] == "withheld"
    assert mpdsr["structured_cause_mentions"] == []

"""MPDSR privacy: identifying content is never retained, even under an approved source field.

Covers the corrective work package F: the free-text cause fallback is gone, causes are only
approved taxonomy codes (and are dropped while no taxonomy is approved), every approved field
has a strict format, and the event cache with its UIDs disappears after 24 hours.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update

from app.domain import retention
from app.domain.mpdsr_cause_taxonomy import APPROVED_CAUSE_TAXONOMY, CauseTaxonomy
from app.domain.mpdsr_minimisation import (
    APPROVED_EVENT_SEMANTIC_FIELDS,
    DROP_INVALID_FORMAT,
    DROP_NO_TAXONOMY,
    DROP_TOO_MANY_ITEMS,
    minimise_event_values,
    normalise_event_date,
)
from app.integrations.dhis2.types import EventObservation
from app.models import (
    DataQualityFlag,
    EventFieldMapping,
    OrgUnit,
    OrgUnitMapping,
    Programme,
    RawEventSnapshot,
    SyncJob,
)
from app.services.purge import purge_policy
from app.services.sync import persist_event_observations

TAXONOMY = CauseTaxonomy(
    version="test-only",
    approval_reference="synthetic test fixture, not an approved taxonomy",
    labels={"O72": "Test category A", "O15": "Test category B"},
)

HOSTILE_VALUES = [
    "Jane",
    "Jane Doe",
    "Nakato",
    "+256700000000",
    "0772 123 456",
    "0772123456",
    "jane.doe@example.org",
    "Kitgum HC IV",
    "Plot 4, Pader Town",
    "Ward 3 bed 12",
    "PADER_HC_III",
    "CM123456789",
    "The mother arrived late after a long journey and was seen by the midwife.",
    "2025-01-04 Jane",
    "2025-01-04T10:00 seen by Dr Okello",
    {"name": "Jane"},
    {"nested": {"phone": "+256700000000"}},
    ["Jane", "Doe"],
    [{"mother": "Jane"}],
    256700000000,
    3.5,
    True,
]

MARKERS = (
    "Jane",
    "Doe",
    "Nakato",
    "256700000000",
    "0772",
    "example.org",
    "Kitgum",
    "Plot",
    "Ward",
    "PADER",
    "CM123",
    "midwife",
    "Okello",
    "mother",
    "phone",
    "name",
)


def _encoded(values: dict) -> str:
    return json.dumps(values, default=str)


@pytest.mark.parametrize("field", sorted(APPROVED_EVENT_SEMANTIC_FIELDS))
@pytest.mark.parametrize("hostile", HOSTILE_VALUES, ids=lambda value: type(value).__name__ + ":" + str(value)[:18])
def test_identifying_values_under_any_approved_field_are_dropped(field, hostile):
    result = minimise_event_values({field: hostile}, taxonomy=TAXONOMY)
    assert field not in result.values, result.values
    assert field in result.dropped
    encoded = _encoded(result.values) + _encoded(result.dropped)
    for marker in MARKERS:
        assert marker not in encoded


def test_a_valid_code_hidden_among_identifiers_keeps_only_the_code():
    result = minimise_event_values(
        {"structured_cause_mentions": ["O72", "Jane Doe", "+256700000000", {"ward": "3"}]}, taxonomy=TAXONOMY
    )
    assert result.values == {"structured_cause_mentions": ["O72"]}


def test_causes_are_dropped_while_no_taxonomy_is_approved():
    assert APPROVED_CAUSE_TAXONOMY is None
    result = minimise_event_values({"structured_cause_mentions": ["O72"], "event_type": "maternal_death"})
    assert result.values == {"event_type": "maternal_death"}
    assert result.dropped == {"structured_cause_mentions": DROP_NO_TAXONOMY}


def test_the_free_text_cause_field_no_longer_exists():
    result = minimise_event_values({"cause_mentions": ["O72"]}, taxonomy=TAXONOMY)
    assert result.values == {}


def test_oversized_cause_lists_are_dropped_not_truncated():
    result = minimise_event_values({"structured_cause_mentions": ["O72"] * 13}, taxonomy=TAXONOMY)
    assert result.values == {}
    assert result.dropped["structured_cause_mentions"] == DROP_TOO_MANY_ITEMS


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2025-01-04", "2025-01-04"),
        ("2025-01-04T13:45:00.000", "2025-01-04"),
        ("2025-01-04T13:45:00Z", "2025-01-04"),
        ("2025-01-04 13:45", "2025-01-04"),
        ("2025-02-30", None),
        ("04/01/2025", None),
        ("2025-1-4", None),
        ("20250104", None),
        ("", None),
    ],
)
def test_dates_are_calendar_dates_without_time_of_day(raw, expected):
    assert normalise_event_date(raw) == expected
    result = minimise_event_values({"death_date": raw})
    if expected is None:
        assert result.dropped["death_date"] == DROP_INVALID_FORMAT
    else:
        assert result.values == {"death_date": expected}


@pytest.mark.parametrize(
    ("value", "kept"),
    [("maternal_death", True), ("perinatal_death", True), ("Maternal Death", False), ("md", False)],
)
def test_event_type_is_a_short_code(value, kept):
    assert ("event_type" in minimise_event_values({"event_type": value}).values) is kept


# ---------------------------------------------------------------------------
# End to end: ingestion, then the 24-hour cache expiry
# ---------------------------------------------------------------------------


@pytest.fixture()
def hostile_mapping_job(session):
    """Mappings that point approved semantic fields at data elements holding identifying data."""
    programme = session.scalar(select(Programme).where(Programme.code == "MPDSR"))
    facility = session.scalar(select(OrgUnit).where(OrgUnit.code == "PADER_HC_III"))
    session.add(
        OrgUnitMapping(
            org_unit_id=facility.id,
            external_uid="TEST_UID_OU_PRIVACY",
            source_system="dhis2",
            valid_from=date(2020, 1, 1),
        )
    )
    mappings = []
    for field_name, uid in (
        ("death_date", "TEST_UID_DE_DEATH"),
        ("notification_date", "TEST_UID_DE_NOTIFY_PHONE"),
        ("review_date", "TEST_UID_DE_REVIEW_PLACE"),
        ("structured_cause_mentions", "TEST_UID_DE_CAUSE_TEXT"),
        ("event_type", "TEST_UID_DE_TYPE_NAME"),
    ):
        mapping = EventFieldMapping(
            programme_id=programme.id,
            program_uid="TEST_UID_PRIVACY_PROGRAM",
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


def test_hostile_values_behind_approved_mappings_are_never_stored_and_expire(session, hostile_mapping_job):
    job, mappings = hostile_mapping_job
    observation = EventObservation(
        event_uid="TEST_UID_EVENT_PRIVACY",
        source_connector="tracker",
        program_uid="TEST_UID_PRIVACY_PROGRAM",
        program_stage_uid=None,
        org_unit_uid="TEST_UID_OU_PRIVACY",
        status="COMPLETED",
        occurred_at=datetime(2025, 1, 4, tzinfo=UTC),
        completed_at=datetime(2025, 1, 6, tzinfo=UTC),
        source_created_at=None,
        source_updated_at=None,
        data_values={
            "TEST_UID_DE_DEATH": "2025-01-04T02:10:00.000",
            "TEST_UID_DE_NOTIFY_PHONE": "+256700000000",
            "TEST_UID_DE_REVIEW_PLACE": "Kitgum HC IV ward 3",
            "TEST_UID_DE_CAUSE_TEXT": ["bled after delivery at home, husband Okello absent", "O72"],
            "TEST_UID_DE_TYPE_NAME": "Jane Doe",
        },
    )
    outcome = persist_event_observations(session, job, [observation], mappings, datetime.now(UTC))
    session.commit()
    assert outcome["stored"] == 1
    row = session.scalar(select(RawEventSnapshot))
    stored = _encoded(row.data_values)
    for marker in ("256700000000", "Kitgum", "ward", "Okello", "Jane", "Doe", "bled", "02:10"):
        assert marker not in stored
    assert row.data_values["death_date"] == "2025-01-04"
    # No taxonomy is approved, so even the valid-looking code is not kept.
    assert "structured_cause_mentions" not in row.data_values
    assert row.notification_date is None and row.review_date is None

    # A quality flag may reference the temporary UID while the cache is live.
    session.add(
        DataQualityFlag(
            rule_id="ACTIVE_MPDSR_WORKFLOW",
            severity="warning",
            explanation="test flag",
            org_unit_id=row.org_unit_id,
            period="FY2024/25",
            event_uid=row.event_uid,
            fingerprint=f"privacy-{uuid4()}",
        )
    )
    session.commit()

    # 25 hours later the event cache, its UID and every reference to it are gone.
    session.execute(update(RawEventSnapshot).values(extracted_at=datetime.now(UTC) - timedelta(hours=25)))
    session.commit()
    result = purge_policy(session, retention.MPDSR_EVENTS, dry_run=False)
    assert result.status == "completed" and result.rows_deleted == 1
    assert session.scalar(select(func.count()).select_from(RawEventSnapshot)) == 0
    assert session.scalar(select(func.count()).where(DataQualityFlag.event_uid == "TEST_UID_EVENT_PRIVACY")) == 0

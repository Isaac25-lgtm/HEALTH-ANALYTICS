"""The data plane is countrywide, and nothing may silently narrow it.

`biostat.pader` is an administrator identity, not a scope. The danger this file guards against is
a national request that quietly resolves to one district — which would look like a working
dashboard while reporting 0.38% of the country. Against the live instance for June 2025, the
national BCG figure is 158,721 and Pader is 600, so the difference between "national" and
"Pader-only" is not subtle, but it is invisible unless something checks.
"""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select

from app.domain.enums import ConnectorType, OrgUnitLevel
from app.integrations.dhis2.aggregate import AggregateAnalyticsAdapter
from app.integrations.dhis2.http import Dhis2HttpClient
from app.integrations.dhis2.tracker import TrackerEventsAdapter
from app.models import OrgUnit, OrgUnitMapping, Programme
from app.services.geography import create_org_unit, descendants
from app.services.hierarchy_authority import DISTRICT_CITY_COHORT
from app.services.mapping_coverage import required_source_keys
from app.services.sync import OrgScopeError, _mapped_org_unit_uids, enqueue_sync_job, execute_sync_job
from tests.test_dhis2_client import _settings
from tests.test_dhis2_extraction_safety import _enabled_settings


def _complete_country_peer_cohort(session, uganda):
    peers = [
        unit
        for unit in descendants(session, uganda)
        if unit.level_type in {OrgUnitLevel.DISTRICT.value, OrgUnitLevel.CITY.value}
    ]
    for index in range(DISTRICT_CITY_COHORT - len(peers)):
        peers.append(
            create_org_unit(
                session,
                code=f"TEST_NATIONAL_{index:03d}",
                name=f"Test national peer {index:03d}",
                level_type=OrgUnitLevel.DISTRICT,
                parent=uganda,
            )
        )
    assert len(peers) == DISTRICT_CITY_COHORT
    return sorted(peers, key=lambda unit: unit.path)


def test_country_root_scope_includes_every_mapped_descendant(session):
    """A country job requests exactly the complete district/city peer cohort."""
    uganda = session.scalar(select(OrgUnit).where(OrgUnit.code == "UG"))
    units = _complete_country_peer_cohort(session, uganda)
    for index, unit in enumerate(units):
        session.add(
            OrgUnitMapping(
                org_unit_id=unit.id,
                source_system="dhis2",
                external_uid=f"TEST_UID_SCOPE_{index}",
            )
        )
    session.flush()

    uids = _mapped_org_unit_uids(session, uganda)

    assert len(uids) == len(units)
    assert len(set(uids)) == len(uids), "a unit must not be requested twice"


def test_a_national_job_cannot_resolve_to_a_single_district(session):
    """One mapped district must fail before a national request reaches DHIS2."""
    uganda = session.scalar(select(OrgUnit).where(OrgUnit.code == "UG"))
    all_units = _complete_country_peer_cohort(session, uganda)
    lone = all_units[-1]
    session.add(
        OrgUnitMapping(org_unit_id=lone.id, source_system="dhis2", external_uid="TEST_UID_ONE_UNIT")
    )
    session.flush()

    with pytest.raises(OrgScopeError) as excinfo:
        _mapped_org_unit_uids(session, uganda)
    assert excinfo.value.code == "org_mapping_incomplete"
    assert "145" in excinfo.value.message


def test_duplicate_effective_uid_is_not_a_proven_regional_scope(session):
    acholi = session.scalar(select(OrgUnit).where(OrgUnit.code == "ACHOLI"))
    peers = [
        unit
        for unit in descendants(session, acholi)
        if unit.level_type in {OrgUnitLevel.DISTRICT.value, OrgUnitLevel.CITY.value}
    ]
    assert len(peers) == 2
    for unit in peers:
        session.add(
            OrgUnitMapping(
                org_unit_id=unit.id,
                source_system="dhis2",
                external_uid="TEST_UID_DUPLICATED_SCOPE",
            )
        )
    session.flush()

    with pytest.raises(OrgScopeError) as excinfo:
        _mapped_org_unit_uids(session, acholi)
    assert excinfo.value.code == "org_mapping_ambiguous"


def test_connectors_preserve_the_service_layer_scope_modes():
    aggregate_requests: list[httpx.Request] = []

    def aggregate_handler(request: httpx.Request) -> httpx.Response:
        aggregate_requests.append(request)
        return httpx.Response(
            200,
            json={
                "headers": [
                    {"name": "dx"},
                    {"name": "ou"},
                    {"name": "pe"},
                    {"name": "value"},
                ],
                "rows": [],
            },
        )

    aggregate_client = Dhis2HttpClient(
        _settings(), transport=httpx.MockTransport(aggregate_handler)
    )
    AggregateAnalyticsAdapter(aggregate_client).fetch(
        dx_uids=["TEST_UID_DX"],
        org_unit_uids=["TEST_UID_PADER", "TEST_UID_KITGUM"],
        periods=["202407"],
        include_descendants=True,
    )
    aggregate_client.close()
    assert [request.url.params["ouMode"] for request in aggregate_requests] == ["SELECTED"]

    tracker_requests: list[httpx.Request] = []

    def tracker_handler(request: httpx.Request) -> httpx.Response:
        tracker_requests.append(request)
        return httpx.Response(
            200, json={"instances": [], "pager": {"page": 1, "pageCount": 1}}
        )

    tracker_client = Dhis2HttpClient(_settings(), transport=httpx.MockTransport(tracker_handler))
    TrackerEventsAdapter(tracker_client).fetch_events_result(
        program_uid="TEST_UID_PROGRAM",
        org_unit_uids=["TEST_UID_PADER", "TEST_UID_KITGUM"],
        ou_mode="DESCENDANTS",
    )
    tracker_client.close()
    assert [request.url.params["ouMode"] for request in tracker_requests] == [
        "DESCENDANTS",
        "DESCENDANTS",
    ]


def test_unmapped_geography_fails_rather_than_reporting_a_narrow_total(session, monkeypatch):
    """No mapping at all must fail loudly; it previously produced a succeeded, empty job."""
    settings = _enabled_settings()
    monkeypatch.setattr("app.services.sync.get_settings", lambda: settings)
    uganda = session.scalar(select(OrgUnit).where(OrgUnit.code == "UG"))
    _complete_country_peer_cohort(session, uganda)
    programme = session.scalar(select(Programme).where(Programme.code == "MNCH"))

    with pytest.raises(OrgScopeError) as excinfo:
        _mapped_org_unit_uids(session, uganda)
    assert excinfo.value.code == "org_mapping_missing"

    job = enqueue_sync_job(
        session,
        org_unit=uganda,
        periods=["202407"],
        user=None,
        job_type=ConnectorType.AGGREGATE.value,
        programme_id=programme.id,
    )
    session.flush()
    executed = execute_sync_job(session, job.id)
    # Source mappings are resolved before geography, so on a bare database the job stops at
    # `mapping_missing`. Either way it fails loudly and stores nothing; what must never happen is
    # a succeeded job carrying a total that covers less than the geography it claims.
    assert executed.status == "failed"
    assert executed.error_code == "mapping_missing"
    assert executed.stored_count in {0, None}


def test_the_catalogue_covers_all_three_national_programmes():
    """Countrywide scope means every programme's keys, not just the one being demonstrated."""
    assert len(required_source_keys("MNCH")) > 0
    assert len(required_source_keys("EPI")) > 0
    assert len(required_source_keys("MPDSR")) > 0
    combined = (
        required_source_keys("MNCH") | required_source_keys("EPI") | required_source_keys("MPDSR")
    )
    assert len(combined) == 48

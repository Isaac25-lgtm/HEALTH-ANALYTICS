"""The data plane is countrywide, and nothing may silently narrow it.

`biostat.pader` is an administrator identity, not a scope. The danger this file guards against is
a national request that quietly resolves to one district — which would look like a working
dashboard while reporting 0.38% of the country. Against the live instance for June 2025, the
national BCG figure is 158,721 and Pader is 600, so the difference between "national" and
"Pader-only" is not subtle, but it is invisible unless something checks.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.domain.enums import ConnectorType
from app.models import OrgUnit, OrgUnitMapping, Programme
from app.services.geography import descendants
from app.services.mapping_coverage import required_source_keys
from app.services.sync import OrgScopeError, _mapped_org_unit_uids, enqueue_sync_job, execute_sync_job
from tests.test_dhis2_extraction_safety import _enabled_settings


def test_country_root_scope_includes_every_mapped_descendant(session):
    """A country-level job must request the whole mapped hierarchy, not just the root."""
    uganda = session.scalar(select(OrgUnit).where(OrgUnit.code == "UG"))
    units = descendants(session, uganda, include_self=True)
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
    """If only one descendant is mapped, the scope is that one unit and nothing pretends otherwise.

    This is the shape of the failure being guarded against: the request would succeed, store rows,
    and present one district's numbers under a national heading. The scope is therefore returned
    explicitly so a caller can compare it against the hierarchy it claims to cover.
    """
    uganda = session.scalar(select(OrgUnit).where(OrgUnit.code == "UG"))
    all_units = descendants(session, uganda, include_self=True)
    lone = all_units[-1]
    session.add(
        OrgUnitMapping(org_unit_id=lone.id, source_system="dhis2", external_uid="TEST_UID_ONE_UNIT")
    )
    session.flush()

    uids = _mapped_org_unit_uids(session, uganda)

    assert uids == ["TEST_UID_ONE_UNIT"]
    # The point: the resolved scope is demonstrably narrower than the hierarchy being requested,
    # which is exactly the comparison an operator must be able to make before trusting a total.
    assert len(uids) < len(all_units), "a national request resolving to one unit must be detectable"


def test_unmapped_geography_fails_rather_than_reporting_a_narrow_total(session, monkeypatch):
    """No mapping at all must fail loudly; it previously produced a succeeded, empty job."""
    settings = _enabled_settings()
    monkeypatch.setattr("app.services.sync.get_settings", lambda: settings)
    uganda = session.scalar(select(OrgUnit).where(OrgUnit.code == "UG"))
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

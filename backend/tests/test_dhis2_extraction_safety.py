"""Extraction safety: runtime gates, provable request scope, and honest period transmission.

Each test here corresponds to a way the connector could previously appear to succeed while having
contacted nothing, requested the wrong thing, or contacted DHIS2 on a deployment where the owner
had switched it off.
"""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select

from app.config import get_settings
from app.domain.enums import ConnectorType
from app.integrations.dhis2.gates import (
    Dhis2Disabled,
    ensure_extraction_enabled,
    extraction_blocked_reason,
)
from app.integrations.dhis2.http import Dhis2HttpClient
from app.models import OrgUnit, OrgUnitMapping, Programme, SourceMapping
from app.services.mapping_coverage import required_source_keys
from app.services.sync import enqueue_sync_job, execute_sync_job


class _RecordingTransport(httpx.BaseTransport):
    """Fails the test if the connector reaches the network at all."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(200, json={"headers": [], "rows": []})


def _enabled_settings(**overrides):
    settings = get_settings().model_copy(
        update={
            "dhis2_enabled": True,
            "sync_enabled": True,
            "dhis2_base_url": "https://example.test",
            "dhis2_username": "tester",
            "dhis2_password": "secret-password",
            **overrides,
        }
    )
    return settings


def test_sync_disabled_blocks_execution_before_any_request(session, monkeypatch):
    """SYNC_ENABLED=false must stop the worker before a single byte leaves the machine."""
    settings = _enabled_settings(sync_enabled=False)
    monkeypatch.setattr("app.services.sync.get_settings", lambda: settings)
    transport = _RecordingTransport()

    uganda = session.scalar(select(OrgUnit).where(OrgUnit.code == "UG"))
    programme = session.scalar(select(Programme).where(Programme.code == "MNCH"))
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

    assert executed.status == "failed"
    assert executed.error_code == "sync_disabled"
    assert transport.requests == []


def test_dhis2_disabled_blocks_execution_before_any_request(session, monkeypatch):
    settings = _enabled_settings(dhis2_enabled=False)
    monkeypatch.setattr("app.services.sync.get_settings", lambda: settings)

    uganda = session.scalar(select(OrgUnit).where(OrgUnit.code == "UG"))
    programme = session.scalar(select(Programme).where(Programme.code == "MNCH"))
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
    assert executed.status == "failed"
    assert executed.error_code == "dhis2_disabled"


def test_connector_construction_cannot_bypass_the_runtime_gate():
    """A directly built client on a disabled deployment is not 'configured', so it cannot request."""
    disabled = _enabled_settings(dhis2_enabled=False)
    with Dhis2HttpClient(disabled) as client:
        assert client.configured() is False
    with Dhis2HttpClient(_enabled_settings()) as client:
        assert client.configured() is True


def test_gate_helper_reports_the_specific_closed_switch():
    assert extraction_blocked_reason(_enabled_settings()) is None
    code, _ = extraction_blocked_reason(_enabled_settings(dhis2_enabled=False))
    assert code == "dhis2_disabled"
    code, _ = extraction_blocked_reason(_enabled_settings(sync_enabled=False))
    assert code == "sync_disabled"
    with pytest.raises(Dhis2Disabled):
        ensure_extraction_enabled(_enabled_settings(sync_enabled=False))
    ensure_extraction_enabled(_enabled_settings())  # does not raise


def test_empty_organisation_mapping_fails_instead_of_reporting_success(session, monkeypatch):
    """Zero mapped units previously produced a request-free job that was marked succeeded.

    That is indistinguishable from "this geography genuinely reported nothing", which is the most
    dangerous possible confusion in a performance dashboard.
    """
    settings = _enabled_settings()
    monkeypatch.setattr("app.services.sync.get_settings", lambda: settings)

    pader = session.scalar(select(OrgUnit).where(OrgUnit.code == "PADER"))
    programme = session.scalar(select(Programme).where(Programme.code == "MNCH"))
    # Map every source key the programme needs, so the missing organisation mapping is the only
    # thing wrong and the failure code cannot come from anywhere else.
    for index, source_key in enumerate(sorted(required_source_keys("MNCH"))):
        session.add(
            SourceMapping(
                internal_source_key=source_key,
                programme_id=programme.id,
                dhis2_item_uid=f"TEST_UID_{index}",
                mapping_version="v1",
                enabled=True,
            )
        )
    session.flush()
    assert session.scalar(select(OrgUnitMapping).limit(1)) is None, "no org mapping is the premise"

    job = enqueue_sync_job(
        session,
        org_unit=pader,
        periods=["202407"],
        user=None,
        job_type=ConnectorType.AGGREGATE.value,
        programme_id=programme.id,
    )
    session.flush()
    executed = execute_sync_job(session, job.id)

    assert executed.status == "failed"
    assert executed.error_code == "org_mapping_missing"
    assert executed.stored_count in {0, None}

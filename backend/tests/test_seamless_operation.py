"""Speed and upkeep changes of 2026-10-10: nothing here may change a calculated value.

A stored run is returned without re-reading its source rows only while no input has changed; a
period roll-up is verified once per data revision; and a deployment without a worker renews its own
data before the MPDSR events expire.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import event, select

from app.config import get_settings
from app.models import (
    AnalyticsRevision,
    CalculationRunMemo,
    OrgUnit,
    Programme,
    RawAggregateValue,
    RollupState,
    SyncJob,
    User,
)
from app.services.dashboard_precompute import default_period, extended_periods
from app.services.local_scheduler import refresh_is_due
from app.services.modules import evaluate_module
from app.services.period_rollup import ensure_period_rollups
from tests.helpers import map_source, put_population, put_raw

FY_MONTHS = [f"2025{m:02d}" for m in range(7, 13)] + [f"2026{m:02d}" for m in range(1, 7)]


def _unit(session, code):
    return session.scalar(select(OrgUnit).where(OrgUnit.code == code))


def _admin(session):
    return session.scalar(select(User).where(User.username == "admin.user"))


def _anc(session, unit):
    return evaluate_module(
        session, user=_admin(session), org_unit_id=unit.id, period="FY2024/25", module="anc", include_children=False
    )


def _entity_loads(session, statements: list[str]):
    """Record statements that load whole source rows (the checksum column is only read that way)."""

    def record(_conn, _cursor, statement, _params, _context, _many):
        if "raw_aggregate_values.checksum" in statement:
            statements.append(statement)

    engine = session.get_bind()
    event.listen(engine, "before_cursor_execute", record)
    return lambda: event.remove(engine, "before_cursor_execute", record)


def test_a_verified_run_is_returned_without_reading_its_source_rows(session):
    acholi = _unit(session, "ACHOLI")
    put_population(session, acholi, 2024, 1_000_000, code="SEAMLESS_2024")
    put_raw(session, acholi, "FY2024/25", "ANC1", 30_000)
    first = _anc(session, acholi)
    revision = session.scalar(select(AnalyticsRevision.revision).where(AnalyticsRevision.key == "global"))
    memos = session.scalars(select(CalculationRunMemo)).all()
    assert memos and all(memo.revision == revision for memo in memos)

    loads: list[str] = []
    stop = _entity_loads(session, loads)
    try:
        second = _anc(session, acholi)
    finally:
        stop()
    assert second["current_run_id"] == first["current_run_id"]
    assert loads == []


def test_a_changed_source_row_is_never_hidden_by_the_verified_run(session):
    acholi = _unit(session, "ACHOLI")
    put_population(session, acholi, 2024, 1_000_000, code="SEAMLESS_2024B")
    put_raw(session, acholi, "FY2024/25", "ANC1", 30_000)
    first = _anc(session, acholi)
    before = next(row for row in first["indicators"] if row["indicator_code"] == "ANC1_COVERAGE")["raw_value"]

    put_raw(session, acholi, "FY2024/25", "ANC1", 45_000)
    second = _anc(session, acholi)
    after = next(row for row in second["indicators"] if row["indicator_code"] == "ANC1_COVERAGE")["raw_value"]

    assert second["current_run_id"] != first["current_run_id"]
    assert after != before
    # And the new result is itself verified for the next identical request.
    assert _anc(session, acholi)["current_run_id"] == second["current_run_id"]


def test_a_regional_figure_does_not_depend_on_facility_rows_loaded_on_demand(session):
    """D-074: above district level a run reads district/city rows only. Facility rows arriving for
    one of its districts leave the regional run untouched; the district itself is recalculated."""
    acholi, pader = _unit(session, "ACHOLI"), _unit(session, "PADER")
    put_population(session, acholi, 2024, 2_000_000, code="SEAMLESS_ACHOLI")
    put_population(session, pader, 2024, 250_000, code="SEAMLESS_PADER")
    put_raw(session, pader, "FY2024/25", "ANC1", 8_000)
    put_raw(session, _unit(session, "KITGUM"), "FY2024/25", "ANC1", 9_000)
    region_first = _anc(session, acholi)
    district_first = _anc(session, pader)

    put_raw(session, _unit(session, "PADER_HC_III"), "FY2024/25", "ANC1", 40)
    region_again = _anc(session, acholi)
    district_again = _anc(session, pader)

    assert region_again["current_run_id"] == region_first["current_run_id"]
    assert district_again["current_run_id"] != district_first["current_run_id"]
    values = lambda result: {row["indicator_code"]: row["raw_value"] for row in result["indicators"]}  # noqa: E731
    assert values(region_again) == values(region_first)


def _month_row(session, unit, programme, month, value):
    row = RawAggregateValue(
        source_system="synthetic_test",
        programme_id=programme.id,
        org_unit_id=unit.id,
        period=month,
        source_metric_id="TEST_UID_ANC1",
        internal_source_key="ANC1",
        dhis2_item_uid="TEST_UID_ANC1",
        value=value,
        extracted_at=datetime.now(UTC),
        mapping_version="v1",
        checksum=f"{unit.code}-{month}-{value}",
        is_current=True,
        value_invalid=False,
    )
    session.add(row)
    session.flush()
    return row


def test_a_roll_up_is_verified_once_per_revision_and_rebuilt_when_a_month_changes(session):
    programme = session.scalar(select(Programme).where(Programme.code == "MNCH"))
    map_source(session, programme.id, "ANC1", "TEST_UID_ANC1")
    pader = _unit(session, "PADER")
    rows = [_month_row(session, pader, programme, month, 10) for month in FY_MONTHS]

    assert ensure_period_rollups(session, ["FY2025/26"]).periods["FY2025/26"]["status"] == "rebuilt"
    # The rebuild itself changed data, so the next call checks once more and records the revision.
    assert ensure_period_rollups(session, ["FY2025/26"]).periods["FY2025/26"]["status"] == "current"
    state = session.get(RollupState, "FY2025/26")
    revision = session.scalar(select(AnalyticsRevision.revision).where(AnalyticsRevision.key == "global"))
    assert state is not None and state.revision == revision

    loads: list[str] = []
    stop = _entity_loads(session, loads)
    try:
        assert ensure_period_rollups(session, ["FY2025/26"]).periods["FY2025/26"]["status"] == "current"
    finally:
        stop()
    assert loads == []

    # A month changes: the stored year must be rebuilt, never served from the earlier verification.
    rows[0].is_current = False
    session.flush()
    _month_row(session, pader, programme, FY_MONTHS[0], 99)
    report = ensure_period_rollups(session, ["FY2025/26"]).periods["FY2025/26"]
    assert report["status"] == "rebuilt"
    year = session.scalar(
        select(RawAggregateValue).where(
            RawAggregateValue.org_unit_id == pader.id,
            RawAggregateValue.period == "FY2025/26",
            RawAggregateValue.internal_source_key == "ANC1",
            RawAggregateValue.is_current.is_(True),
        )
    )
    assert float(year.value) == 99 + 10 * 11


def test_preparation_periods_are_the_landing_year_then_the_year_in_progress_and_two_closed_months():
    assert default_period(date(2026, 10, 10)) == "FY2025/26"
    assert extended_periods(date(2026, 10, 10)) == ["FY2026/27", "202609", "202608"]
    assert default_period(date(2026, 3, 5)) == "FY2024/25"
    assert extended_periods(date(2026, 1, 20)) == ["FY2025/26", "202512", "202511"]


def _tracker_job(session, *, status, finished_at=None, created_at=None, key="scheduled:tracker:test"):
    programme = session.scalar(select(Programme).where(Programme.code == "MPDSR"))
    job = SyncJob(
        job_type="tracker",
        status=status,
        org_unit_id=_unit(session, "UG").id,
        programme_id=programme.id,
        period_from="FY2024/25",
        period_to="FY2026/27",
        mapping_version="v1",
        finished_at=finished_at,
        idempotency_key=key,
    )
    session.add(job)
    session.flush()
    if created_at is not None:
        job.created_at = created_at
        session.flush()
    return job


def test_the_local_scheduler_refreshes_before_the_event_cache_expires(session):
    now = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
    enabled = get_settings().model_copy(
        update={
            "dhis2_enabled": True,
            "sync_enabled": True,
            "dhis2_refresh_schedule_enabled": True,
            "dhis2_refresh_interval_hours": 20,
        }
    )
    # The interval must leave room to finish before the events expire.
    assert enabled.dhis2_refresh_interval_hours < enabled.mpdsr_event_retention_hours

    assert refresh_is_due(session, enabled.model_copy(update={"dhis2_refresh_schedule_enabled": False}), now) is False
    assert refresh_is_due(session, enabled.model_copy(update={"sync_enabled": False}), now) is False
    # Never refreshed: due at once.
    assert refresh_is_due(session, enabled, now) is True

    _tracker_job(
        session,
        status="succeeded",
        finished_at=now - timedelta(hours=3),
        created_at=now - timedelta(hours=4),
        key="scheduled:tracker:a",
    )
    assert refresh_is_due(session, enabled, now) is False
    assert refresh_is_due(session, enabled, now + timedelta(hours=17, minutes=1)) is True

    # A refresh already in progress is not started twice; an abandoned one does not block for ever.
    _tracker_job(session, status="running", created_at=now + timedelta(hours=18), key="scheduled:tracker:b")
    assert refresh_is_due(session, enabled, now + timedelta(hours=18, minutes=30)) is False
    assert refresh_is_due(session, enabled, now + timedelta(hours=22)) is True

    # A failed attempt is not repeated every few minutes against a struggling source server.
    _tracker_job(session, status="failed", created_at=now + timedelta(hours=23), key="scheduled:tracker:c")
    assert refresh_is_due(session, enabled, now + timedelta(hours=23, minutes=30)) is False
    assert refresh_is_due(session, enabled, now + timedelta(hours=25, minutes=1)) is True


def test_tracker_events_are_fetched_several_peers_at_a_time_in_a_fixed_order():
    """Pages end at a short page (no total count is requested) and the result keeps peer order."""
    import threading
    import time

    import httpx

    from app.integrations.dhis2.http import Dhis2HttpClient
    from app.integrations.dhis2.tracker import TrackerEventsAdapter
    from tests.test_dhis2_client import _settings

    peers = [f"TEST_UID_PEER{index}" for index in range(6)]
    requests: list[httpx.Request] = []
    lock = threading.Lock()

    def handler(request: httpx.Request) -> httpx.Response:
        with lock:
            requests.append(request)
        peer = request.url.params["orgUnit"]
        page = int(request.url.params["page"])
        # Later peers answer sooner, so arrival order differs from request order.
        time.sleep(0.02 * (len(peers) - peers.index(peer)))
        count = 2 if page == 1 else 1
        return httpx.Response(
            200,
            json={
                "instances": [
                    {"event": f"{peer}-P{page}-{n}", "orgUnit": peer, "status": "COMPLETED", "dataValues": []}
                    for n in range(count)
                ],
                "pager": {"page": page, "pageSize": 2},
            },
        )

    checking = {"active": 0, "overlapped": False}

    def cancelled() -> bool:
        checking["active"] += 1
        if checking["active"] > 1:
            checking["overlapped"] = True
        time.sleep(0.001)
        checking["active"] -= 1
        return False

    settings = _settings(dhis2_page_size=2, dhis2_max_pages=5, dhis2_tracker_parallel_requests=4)
    client = Dhis2HttpClient(settings, transport=httpx.MockTransport(handler), cancelled=cancelled)
    result = TrackerEventsAdapter(client).fetch_events_result(
        program_uid="TEST_UID_PROGRAM", org_unit_uids=peers, ou_mode="DESCENDANTS"
    )
    client.close()

    assert result.page_limit_reached is False
    assert result.pages_fetched == 2 * len(peers)
    assert [row.event_uid for row in result.observations] == [
        f"{peer}-P{page}-{n}" for peer in peers for page, count in ((1, 2), (2, 1)) for n in range(count)
    ]
    assert all("totalPages" not in request.url.params for request in requests)
    # The cancellation check uses the caller's database session: never from two threads at once.
    assert checking["overlapped"] is False

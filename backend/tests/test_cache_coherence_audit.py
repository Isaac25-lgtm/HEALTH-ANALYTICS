"""Reproductions from the independent audit of 2026-10-11, kept as regression tests.

Codex's audit (docs/project-context/CODEX_AUDIT_2026-10-11.md) showed that the fast paths added on
2026-10-10 could return a stale or wrong result. Each case here failed before the corrections of
2026-10-11 and must keep passing:

- a yearly total verified while a month was being replaced, then read at the newer revision;
- a stored run carrying a fingerprint of rows other than the ones it was calculated from;
- a reporting-units (D-067) result surviving a change in extraction coverage;
- an event change committed out of order that moved no count or maximum timestamp;
- a refresh started twice, a short page ending retrieval early, a stale source not re-scanned.

Fixtures are isolated test inputs, never Uganda measurements. The PostgreSQL variants run only
against the disposable cluster named by HPIP_POSTGRES_TEST_URL.
"""

import os
import time
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models import (
    AnalyticsRevision,
    CalculatedValue,
    EventFieldMapping,
    OrgUnit,
    OrgUnitMapping,
    Programme,
    RawAggregateValue,
    RawEventSnapshot,
    SyncJob,
)
from app.services import calculation as calc
from app.services import local_scheduler, period_rollup, sync
from app.services.seed import seed_reference_data
from tests.conftest import SEED_PASSWORD
from tests.helpers import map_source, put_event, put_population, put_raw


def record(case, **data):
    """Kept from the audit harness; the assertions carry the meaning."""


@contextmanager
def _database(kind: str):
    admin = None
    name = None
    if kind == "postgres":
        admin_url = os.environ.get("HPIP_POSTGRES_TEST_URL", "")
        if not admin_url:
            pytest.skip("HPIP_POSTGRES_TEST_URL is not set; PostgreSQL variant not run")
        admin = create_engine(admin_url)
        name = "hpip_cache_audit_" + uuid4().hex[:12]
        with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.exec_driver_sql(f'CREATE DATABASE "{name}"')
        engine = create_engine(make_url(admin_url).set(database=name))
    else:
        engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        Base.metadata.create_all(engine)
        with Session(engine, autoflush=False) as session:
            seed_reference_data(session, SEED_PASSWORD)
            session.commit()
            yield session
    finally:
        engine.dispose()
        if admin is not None:
            with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                assert name.startswith("hpip_cache_audit_")
                conn.exec_driver_sql(f'DROP DATABASE "{name}"')
            admin.dispose()


@pytest.fixture(params=["sqlite", "postgres"])
def db(request):
    """Both databases: the behaviour must hold on each."""
    with _database(request.param) as session:
        yield session


@pytest.fixture
def pg():
    """PostgreSQL only, for cases that need real transactions, triggers or advisory locks.

    A separate fixture rather than a skipped SQLite variant: CI fails the run on any skip.
    """
    with _database("postgres") as session:
        yield session


def unit(session, code):
    return session.scalar(select(OrgUnit).where(OrgUnit.code == code))


def programme(session, code):
    return session.scalar(select(Programme).where(Programme.code == code))


def value(session, run):
    return session.scalar(select(CalculatedValue).where(CalculatedValue.calculation_run_id == run.id))


def calculate(session, target, period, pcode, code, *, reuse=True):
    calc.clear_calculation_batch(session)
    if reuse:
        calc.prepare_calculation_batch(session, org_unit=target, periods=[period], programme_codes=[pcode])
    run = calc.run_calculation(
        session, org_unit=target, period=period, user=None, programme_codes=[pcode], indicator_codes=[code]
    )
    calc.flush_run_memos(session)
    session.commit()
    return run, value(session, run)


@pytest.mark.parametrize("code", ["MV1_COVERAGE", "MV2_COVERAGE", "MV3_COVERAGE", "MV4_COVERAGE", "MV1_MV4_DROPOUT"])
@pytest.mark.parametrize("initial_coverage", [True, False])
def test_coverage_change_must_not_keep_an_available_number(db, code, initial_coverage):
    country, pader, epi = unit(db, "UG"), unit(db, "PADER"), programme(db, "EPI")
    put_population(db, country, 2024, 1_000_000, code="TEST_ONLY_AUDIT_POP")
    put_raw(db, pader, "FY2024/25", "MV1", 4300)
    put_raw(db, pader, "FY2024/25", "MV2", 4300)
    put_raw(db, pader, "FY2024/25", "MV3", 4300)
    put_raw(db, pader, "FY2024/25", "MV4", 2150)
    peers = [u for u in calc.descendants(db, country) if u.level_type in {"district", "city"}]
    months = [f"2024{m:02d}" for m in range(7, 13)] + [f"2025{m:02d}" for m in range(1, 7)]
    job = SyncJob(
        job_type="aggregate",
        status="succeeded" if initial_coverage else "queued",
        programme_id=epi.id,
        org_unit_id=country.id,
        mapping_version="v1",
        period_from=months[0],
        period_to=months[-1],
        coverage_manifest={
            "complete": True,
            "periods": months,
            "source_keys": ["MV1", "MV2", "MV3", "MV4"],
            "org_unit_ids": [str(u.id) for u in peers],
        },
    )
    db.add(job)
    db.commit()
    first, first_value = calculate(db, country, "FY2024/25", "EPI", code)
    assert (first_value.raw_value is not None) == initial_coverage
    if initial_coverage:
        job.cancelled = True
    else:
        job.status = "succeeded"
    db.commit()
    reused, reused_value = calculate(db, country, "FY2024/25", "EPI", code)
    fresh, fresh_value = calculate(db, country, "FY2024/25", "EPI", code, reuse=False)
    record(
        "coverage_invalidated",
        backend=db.bind.dialect.name,
        indicator=code,
        initial_coverage=initial_coverage,
        before=first_value.raw_value,
        cached=reused_value.raw_value,
        fresh=fresh_value.raw_value,
        same_run=first.id == reused.id,
        fresh_reason=fresh_value.reason_code,
    )
    assert reused_value.raw_value == fresh_value.raw_value, (
        "Cache serves a number without now-required extraction coverage"
    )


def test_fingerprint_before_rows_aba_must_not_publish_intervening_value(pg, monkeypatch):
    db = pg
    target = unit(db, "PADER")
    put_population(db, target, 2024, 1_000_000, code="TEST_ONLY_AUDIT_POP")
    row = put_raw(db, target, "FY2024/25", "ANC1", 10000)
    db.commit()
    row_id = row.id
    db.expunge(row)
    original = calc._source_digests
    armed = [True]

    def interleave(session, batch):
        digest = original(session, batch)
        if armed[0]:
            armed[0] = False
            with session.get_bind().begin() as writer:
                writer.execute(update(RawAggregateValue).where(RawAggregateValue.id == row_id).values(value=20000))
        return digest

    monkeypatch.setattr(calc, "_source_digests", interleave)
    first, first_value = calculate(db, target, "FY2024/25", "MNCH", "ANC1_COVERAGE")
    assert first_value.raw_value == 40
    monkeypatch.setattr(calc, "_source_digests", original)
    with db.bind.begin() as writer:
        writer.execute(update(RawAggregateValue).where(RawAggregateValue.id == row_id).values(value=10000))
    db.expire_all()
    cached, cached_value = calculate(db, target, "FY2024/25", "MNCH", "ANC1_COVERAGE")
    fresh, fresh_value = calculate(db, target, "FY2024/25", "MNCH", "ANC1_COVERAGE", reuse=False)
    record(
        "fingerprint_row_aba",
        cached=cached_value.raw_value,
        fresh=fresh_value.raw_value,
        same_run=cached.id == first.id,
    )
    assert cached_value.raw_value == fresh_value.raw_value, (
        "Fingerprint A was stamped on result B and trusted when source returned to A"
    )


def test_event_state_must_detect_an_out_of_order_commit(pg):
    db = pg
    pader = unit(db, "PADER")
    events = [
        put_event(
            db, pader, death_date=date(2024, 8, d), status="COMPLETED", data_values={"event_type": "maternal_review"}
        )
        for d in (1, 2, 3)
    ]
    db.commit()
    ids = [e.id for e in events]
    # Older transaction starts before a different event's newer committed update.
    older = db.bind.connect()
    transaction = older.begin()
    older.exec_driver_sql("SELECT CURRENT_TIMESTAMP")
    time.sleep(0.02)
    with db.bind.begin() as newer:
        newer.execute(update(RawEventSnapshot).where(RawEventSnapshot.id == ids[2]).values(status="COMPLETED"))
    db.expire_all()
    before = calc._event_state(db, {})
    first, first_value = calculate(db, unit(db, "UG"), "FY2024/25", "MPDSR", "MATERNAL_REVIEWED_COUNT")
    assert first_value.raw_value == 3
    older.execute(update(RawEventSnapshot).where(RawEventSnapshot.id == ids[0]).values(death_date=date(2025, 8, 1)))
    transaction.commit()
    older.close()
    after = calc._event_state(db, {})
    db.expire_all()
    cached, cached_value = calculate(db, unit(db, "UG"), "FY2024/25", "MPDSR", "MATERNAL_REVIEWED_COUNT")
    fresh, fresh_value = calculate(db, unit(db, "UG"), "FY2024/25", "MPDSR", "MATERNAL_REVIEWED_COUNT", reuse=False)
    record(
        "event_state_out_of_order",
        digest_unchanged=before["digest"] == after["digest"],
        valid_until_unchanged=before["valid_until"] == after["valid_until"],
        cached=cached_value.raw_value,
        fresh=fresh_value.raw_value,
        same_run=first.id == cached.id,
    )
    assert before["digest"] != after["digest"], (
        "An event left the death cohort, but the aggregate change detector did not change"
    )


def test_scoped_rollup_cannot_skip_new_coverage(pg):
    db = pg
    pader, kitgum = unit(db, "PADER"), unit(db, "KITGUM")
    mnch = programme(db, "MNCH")
    map_source(db, mnch.id, "ANC1", "TEST_ONLY_AUDIT_ANC1")
    months = [f"2024{m:02d}" for m in range(7, 13)] + [f"2025{m:02d}" for m in range(1, 7)]
    for m in months[:-1]:
        put_raw(db, pader, m, "ANC1", 10)
    for m in months:
        put_raw(db, kitgum, m, "ANC1", 3)
    db.commit()
    period_rollup.ensure_period_rollups(db, ["FY2024/25"])
    db.commit()
    period_rollup.ensure_period_rollups(db, ["FY2024/25"])
    db.commit()
    job = SyncJob(
        job_type="aggregate",
        status="succeeded",
        org_unit_id=pader.id,
        programme_id=mnch.id,
        mapping_version="v1",
        period_from=months[-1],
        period_to=months[-1],
        coverage_manifest={
            "complete": True,
            "source_keys": ["ANC1"],
            "periods": [months[-1]],
            "org_unit_ids": [str(pader.id)],
            "requests": [{"source_key": "ANC1", "periods": [months[-1]], "org_unit_ids": [str(pader.id)]}],
        },
    )
    db.add(job)
    db.commit()
    report = period_rollup.ensure_period_rollups(db, ["FY2024/25"])
    db.commit()
    result = db.scalar(
        select(RawAggregateValue).where(
            RawAggregateValue.org_unit_id == pader.id,
            RawAggregateValue.period == "FY2024/25",
            RawAggregateValue.is_current.is_(True),
        )
    )
    record("scoped_rollup_new_coverage", report=report.periods, value=result.value if result else None)
    assert result is not None and result.value == 110
    job.cancelled = True
    db.commit()
    period_rollup.ensure_period_rollups(db, ["FY2024/25"])
    db.commit()
    assert not db.scalar(
        select(RawAggregateValue).where(
            RawAggregateValue.org_unit_id == pader.id,
            RawAggregateValue.period == "FY2024/25",
            RawAggregateValue.is_current.is_(True),
        )
    )


def test_manifest_cannot_certify_units_outside_its_outer_list(db):
    pader, kitgum = unit(db, "PADER"), unit(db, "KITGUM")
    p = programme(db, "MNCH")
    job = SimpleNamespace(
        programme_id=p.id,
        mapping_version="v1",
        coverage_manifest={
            "complete": True,
            "source_keys": ["ANC1"],
            "org_unit_ids": [str(kitgum.id)],
            "requests": [{"source_key": "ANC1", "org_unit_ids": [str(pader.id)], "periods": ["202506"]}],
        },
    )
    assert period_rollup._missing_month_coverage([job], p.id, pader.id, "ANC1", "v1", {"202506"}) is None


def test_rollup_scope_cannot_skip_a_concurrent_month_replacement(pg, monkeypatch):
    db = pg
    target, mnch = unit(db, "PADER"), programme(db, "MNCH")
    map_source(db, mnch.id, "ANC1", "TEST_ONLY_AUDIT_ANC1")
    months = [f"2024{m:02d}" for m in range(7, 13)] + [f"2025{m:02d}" for m in range(1, 7)]
    rows = [put_raw(db, target, m, "ANC1", 10) for m in months]
    row_id = rows[0].id
    db.commit()
    period_rollup.ensure_period_rollups(db, ["FY2024/25"])
    db.commit()
    period_rollup.ensure_period_rollups(db, ["FY2024/25"])
    db.commit()
    put_raw(db, unit(db, "KITGUM"), "202401", "ANC1", 7)
    db.commit()
    original = period_rollup._unit_digests
    armed = [True]

    def replace_after_digest(session, period, period_months):
        digests = original(session, period, period_months)
        if armed[0]:
            armed[0] = False
            with Session(session.bind, autoflush=False) as writer:
                old = writer.get(RawAggregateValue, row_id)
                old.is_current = False
                writer.flush()
                writer.add(
                    RawAggregateValue(
                        source_system=old.source_system,
                        programme_id=old.programme_id,
                        org_unit_id=old.org_unit_id,
                        period=old.period,
                        internal_source_key=old.internal_source_key,
                        source_metric_id=old.source_metric_id,
                        dhis2_item_uid=old.dhis2_item_uid,
                        category_option_combo_uid=old.category_option_combo_uid,
                        mapping_version=old.mapping_version,
                        value=99,
                        extracted_at=datetime.now(UTC),
                        checksum="TEST_ONLY_REPLACEMENT",
                        is_current=True,
                    )
                )
                writer.commit()
        return digests

    monkeypatch.setattr(period_rollup, "_unit_digests", replace_after_digest)
    report = period_rollup.ensure_period_rollups(db, ["FY2024/25"])
    db.commit()
    derived = db.scalar(
        select(RawAggregateValue).where(
            RawAggregateValue.org_unit_id == target.id,
            RawAggregateValue.period == "FY2024/25",
            RawAggregateValue.is_current.is_(True),
        )
    )
    expected = sum(
        db.scalars(
            select(RawAggregateValue.value).where(
                RawAggregateValue.org_unit_id == target.id,
                RawAggregateValue.period.in_(months),
                RawAggregateValue.is_current.is_(True),
            )
        )
    )
    calc.clear_calculation_batch(db)
    batch = calc.prepare_calculation_batch(db, org_unit=target, periods=["FY2024/25"], programme_codes=["MNCH"])
    record(
        "rollup_concurrent_replacement",
        derived=derived.value,
        expected=expected,
        report=report.periods,
        calculation_revision=batch["input_revision"],
    )
    assert derived.value == expected, (
        "Scoped verification skipped a changed unit and calculation now reads the stale year at the new revision"
    )


def test_statement_triggers_bump_once_and_skip_zero_rows(pg):
    db = pg
    target = unit(db, "PADER")
    for key in ("ANC1", "ANC4"):
        put_raw(db, target, "202506", key, 10)
    db.commit()
    def rev():
        return db.scalar(select(AnalyticsRevision.revision).where(AnalyticsRevision.key == "global"))

    before = rev()
    db.execute(update(RawAggregateValue).where(RawAggregateValue.org_unit_id == target.id).values(value=11))
    db.commit()
    assert rev() == before + 1
    before = rev()
    db.execute(update(RawAggregateValue).where(RawAggregateValue.id == uuid4()).values(value=15))
    db.commit()
    assert rev() == before


def test_scheduler_two_processes_cannot_both_spawn(db, monkeypatch):
    from app.config import Settings

    settings = Settings(
        _env_file=None,
        app_env="test",
        dhis2_enabled=True,
        sync_enabled=True,
        dhis2_refresh_schedule_enabled=True,
        sync_execution="eager",
    )
    calls = []

    # No subprocess starts; both schedulers make their real decisions against the fixture store.
    class Context:
        def __enter__(self):
            return db

        def __exit__(self, *args):
            pass

    monkeypatch.setattr("app.db.session.get_session_factory", lambda: lambda: Context())
    monkeypatch.setattr(local_scheduler, "get_settings", lambda: settings)
    monkeypatch.setattr(
        local_scheduler.subprocess, "Popen", lambda *a, **k: calls.append(1) or SimpleNamespace(poll=lambda: None)
    )
    first, second = local_scheduler.LocalRefreshScheduler(), local_scheduler.LocalRefreshScheduler()
    outcomes = [first.check_once(), second.check_once()]
    record("scheduler_two_instances", spawned=len(calls), decisions=outcomes)
    assert len(calls) == 1, "Two API scheduler instances both started a refresh"


def test_parallel_paging_respects_server_reported_page_size():
    from app.integrations.dhis2.tracker import TrackerEventsAdapter

    calls = []

    class Client:
        settings = SimpleNamespace(
            dhis2_api_path_prefix="/api",
            dhis2_page_size=2,
            dhis2_ou_mode="DESCENDANTS",
            dhis2_max_pages=10,
            dhis2_tracker_parallel_requests=2,
        )
        _cancelled = staticmethod(lambda: False)

        def get_json(self, _path, params):
            calls.append(params["page"])
            return {
                "pager": {"page": params["page"], "pageSize": 1},
                "instances": [
                    {
                        "event": "TEST_ONLY_PAGE_" + str(params["page"]),
                        "orgUnit": "TEST_ONLY_UNIT",
                        "status": "COMPLETED",
                    }
                ]
                if params["page"] <= 2
                else [],
            }

    result = TrackerEventsAdapter(Client()).fetch_events_result(
        program_uid="TEST_ONLY_PROGRAM", org_unit_uids=["TEST_ONLY_UNIT"]
    )
    record("server_page_size", calls=calls, received=len(result.observations), truncated=result.page_limit_reached)
    assert len(result.observations) == 2, "Short-page stop used requested size rather than server's page size"


def test_bulk_duplicates_keep_last_event_and_withdraw_only_unseen(db):
    from app.integrations.dhis2.types import EventObservation
    from app.services.sync_reconciliation import reconcile_event_withdrawals

    pader, mpdsr = unit(db, "PADER"), programme(db, "MPDSR")
    db.add(OrgUnitMapping(org_unit_id=pader.id, source_system="dhis2", external_uid="TEST_ONLY_BULK_UNIT"))
    mapping = EventFieldMapping(
        programme_id=mpdsr.id,
        program_uid="TEST_ONLY_BULK_FORM",
        source_data_element_uid="TEST_ONLY_DEATH_DATE",
        internal_semantic_field="death_date",
        event_type="maternal_review",
        mapping_version="v1",
        enabled=True,
    )
    db.add(mapping)
    missing = put_event(
        db,
        pader,
        programme_id=mpdsr.id,
        program_uid="TEST_ONLY_BULK_FORM",
        death_date=date(2025, 6, 3),
        data_values={"event_type": "maternal_review"},
    )
    missing.mapping_version = "v1"
    missing.occurred_at = datetime(2025, 6, 3, tzinfo=UTC)
    missing.extracted_at = datetime.now(UTC) - timedelta(minutes=1)
    job = SyncJob(
        job_type="tracker",
        status="running",
        org_unit_id=pader.id,
        programme_id=mpdsr.id,
        mapping_version="v1",
        started_at=datetime.now(UTC),
        window_start=date(2025, 6, 1),
        window_end=date(2025, 6, 30),
    )
    db.add(job)
    db.flush()

    def observation(day):
        return EventObservation(
            event_uid="TEST_ONLY_DUPLICATE",
            source_connector="tracker",
            program_uid=mapping.program_uid,
            program_stage_uid=None,
            org_unit_uid="TEST_ONLY_BULK_UNIT",
            status="COMPLETED",
            occurred_at=datetime(2025, 6, day, tzinfo=UTC),
            completed_at=None,
            source_created_at=None,
            source_updated_at=None,
            data_values={"TEST_ONLY_DEATH_DATE": f"2025-06-{day:02d}"},
        )

    seen = set()
    counts = sync.persist_event_observations(
        db, job, [observation(1), observation(2)], [mapping], datetime.now(UTC), seen_row_ids=seen
    )
    job.status = "succeeded"
    job.coverage_manifest = {"complete": True}
    removed = reconcile_event_withdrawals(
        db, job, seen_row_ids=seen, root_ids={pader.id}, program_uids={mapping.program_uid}
    )
    current = db.scalars(select(RawEventSnapshot).where(RawEventSnapshot.is_current.is_(True))).all()
    record("bulk_duplicates", stored=counts["stored"], distinct_seen=len(seen), current=len(current), withdrawn=removed)
    assert counts["stored"] == 2 and len(seen) == 1 and removed == 1
    assert len(current) == 1 and current[0].death_date == date(2025, 6, 2)


def test_quality_reuse_does_not_hide_a_clock_crossing_staleness(db, monkeypatch):
    from app.config import get_settings
    from app.services import quality

    target = unit(db, "PADER")
    now = datetime.now(UTC)
    previous_month = now.date().replace(day=1) - timedelta(days=1)
    period = previous_month.strftime("%Y%m")
    put_population(db, target, previous_month.year, 1_000_000, code="TEST_ONLY_QUALITY_POP")
    row = put_raw(db, target, period, "ANC1", 100)
    row.extracted_at = now - timedelta(hours=get_settings().dhis2_stale_hours, minutes=-10)
    db.commit()
    calc.clear_calculation_batch(db)
    calc.prepare_calculation_batch(db, org_unit=target, periods=[period], programme_codes=["MNCH"])
    run = calc.run_calculation(
        db, org_unit=target, period=period, user=None, programme_codes=["MNCH"], indicator_codes=["ANC1_COVERAGE"]
    )
    quality.scan_quality(db, org_unit=target, period=period, calculation_run=run)
    calc.note_quality_scanned(db, run)
    calc.flush_run_memos(db)
    db.commit()

    class Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return now + timedelta(minutes=20)

    monkeypatch.setattr(calc, "datetime", Later)
    monkeypatch.setattr(quality, "datetime", Later)
    calc.clear_calculation_batch(db)
    calc.prepare_calculation_batch(db, org_unit=target, periods=[period], programme_codes=["MNCH"])
    again = calc.run_calculation(
        db, org_unit=target, period=period, user=None, programme_codes=["MNCH"], indicator_codes=["ANC1_COVERAGE"]
    )
    recent = calc.quality_scan_is_recent(db, again)
    enabled = quality._enabled_rules(db)
    new = [
        flag
        for flag in quality._scan_stale_and_spike(db, target, period, again, enabled)
        if flag and flag.rule_id == "STALE_REPORTING"
    ]
    record("quality_clock_crossing", skip_scan=recent, stale_flags_fresh_scan=len(new), same_run=again.id == run.id)
    assert not (recent and new), "A clock-only newly stale source still skips its quality scan"


def test_parallel_requests_restore_callback_and_preserve_peer_order():
    import threading

    from app.integrations.dhis2.tracker import TrackerEventsAdapter

    lock = threading.Lock()
    active = [0, 0]

    def cancelled():
        with lock:
            active[0] += 1
            active[1] = max(active[1], active[0])
        time.sleep(0.005)
        with lock:
            active[0] -= 1
        return False

    class Client:
        settings = SimpleNamespace(
            dhis2_api_path_prefix="/api",
            dhis2_page_size=100,
            dhis2_ou_mode="DESCENDANTS",
            dhis2_max_pages=10,
            dhis2_tracker_parallel_requests=2,
        )

        def get_json(self, _path, params):
            assert not self._cancelled()
            return {"instances": [{"event": "TEST_ONLY_" + params["orgUnit"], "orgUnit": params["orgUnit"]}]}

    client = Client()
    client._cancelled = cancelled
    targets = ["TEST_ONLY_PEER_A", "TEST_ONLY_PEER_B"]
    result = TrackerEventsAdapter(client).fetch_events_result(program_uid="TEST_ONLY_FORM", org_unit_uids=targets)
    assert active[1] == 1 and client._cancelled is cancelled
    assert [row.org_unit_uid for row in result.observations] == targets


def test_an_interrupted_job_is_released_and_a_running_one_is_left_alone(pg):
    """A job left "running" by a dead process blocks the same request for ever; one whose process
    still holds the execution lock must never be touched."""
    db = pg
    pader, mnch = unit(db, "PADER"), programme(db, "MNCH")
    long_ago = datetime.now(UTC) - timedelta(hours=1)

    def job(**values):
        row = SyncJob(
            job_type="aggregate_facilities",
            status="running",
            org_unit_id=pader.id,
            programme_id=mnch.id,
            mapping_version="v1",
            started_at=long_ago,
            **values,
        )
        db.add(row)
        db.flush()
        return row.id

    dead = job(idempotency_key="facility:TEST_ONLY_DEAD")
    alive = job(idempotency_key="facility:TEST_ONLY_ALIVE")
    recent = job(idempotency_key="facility:TEST_ONLY_RECENT")
    manual = job(idempotency_key=None)
    db.execute(update(SyncJob).where(SyncJob.id == recent).values(started_at=datetime.now(UTC)))
    db.execute(update(SyncJob).where(SyncJob.id == manual).values(job_type="aggregate"))
    db.commit()

    holder = db.bind.connect()
    try:
        assert holder.exec_driver_sql("SELECT pg_try_advisory_lock(%s)", (sync._sync_lock_key(alive),)).scalar()
        assert sync.reclaim_abandoned_sync_jobs(db) == 1
    finally:
        holder.close()
    db.expire_all()
    states = {row.id: (row.status, row.error_code) for row in db.scalars(select(SyncJob))}
    assert states[dead] == ("failed", "interrupted")
    assert states[alive] == ("running", None)
    assert states[recent] == ("running", None)
    assert states[manual] == ("running", None)

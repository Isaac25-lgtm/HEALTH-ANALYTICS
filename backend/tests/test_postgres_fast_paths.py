"""PostgreSQL-only re-verification by database fingerprint (migration 0020).

A change somewhere else moves the global analytics revision. A stored run, or a period roll-up,
that does not read the changed rows must be recognised as still exact without being recalculated
or re-read; one that does read them must never be served from the earlier result.
"""

from __future__ import annotations

from datetime import UTC, datetime

from alembic import command
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.models import AnalyticsRevision, OrgUnit, Programme, RawAggregateValue, RollupState, User
from app.services.modules import evaluate_module
from app.services.period_rollup import ensure_period_rollups
from app.services.seed import seed_reference_data
from tests.conftest import SEED_PASSWORD
from tests.helpers import map_source, put_population, put_raw
from tests.test_postgres_migrations import (
    _admin_url,
    _alembic_cfg,
    _cleanup,
    _point_alembic,
    _prepare_verify_db,
    requires_postgres,
)

FY_MONTHS = [f"2025{m:02d}" for m in range(7, 13)] + [f"2026{m:02d}" for m in range(1, 7)]


def _unit(session, code):
    return session.scalar(select(OrgUnit).where(OrgUnit.code == code))


def _anc(session, unit):
    admin = session.scalar(select(User).where(User.username == "admin.user"))
    result = evaluate_module(
        session, user=admin, org_unit_id=unit.id, period="FY2024/25", module="anc", include_children=False
    )
    session.commit()
    return result


def _watch_row_loads(engine, statements: list[str]):
    """Record statements that load whole source rows (this column is never part of a fingerprint)."""

    def record(_conn, _cursor, statement, _params, _context, _many):
        # A whole-subtree or whole-period load; a pass scoped to named units is not one.
        if "raw_aggregate_values.dhis2_org_unit_uid" in statement and (
            "org_units.path LIKE" in statement or "org_unit_id IN" not in statement
        ):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    return lambda: event.remove(engine, "before_cursor_execute", record)


def _revisions(session) -> dict:
    return dict(session.execute(select(AnalyticsRevision.key, AnalyticsRevision.revision)).all())


@requires_postgres
def test_a_run_survives_a_change_elsewhere_and_never_a_change_to_its_own_inputs(monkeypatch):
    admin, test_url = _prepare_verify_db(_admin_url())
    _point_alembic(monkeypatch, test_url)
    engine = None
    try:
        command.upgrade(_alembic_cfg(), "head")
        engine = create_engine(test_url, future=True)
        session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()
        seed_reference_data(session, SEED_PASSWORD)
        kitgum, pader, acholi = _unit(session, "KITGUM"), _unit(session, "PADER"), _unit(session, "ACHOLI")
        pader_facility = _unit(session, "PADER_HC_III")
        for unit, population in ((kitgum, 300_000), (pader, 250_000), (acholi, 2_000_000)):
            put_population(session, unit, 2024, population, code=f"FAST_{unit.code}")
        put_raw(session, kitgum, "FY2024/25", "ANC1", 9_000)
        put_raw(session, pader, "FY2024/25", "ANC1", 8_000)
        session.commit()

        kitgum_first = _anc(session, kitgum)
        acholi_first = _anc(session, acholi)
        before = _revisions(session)

        # A facility row arrives in another district: source data changed, configuration did not.
        put_raw(session, pader_facility, "FY2024/25", "ANC1", 40)
        session.commit()
        after = _revisions(session)
        assert after["global"] > before["global"]
        assert after["config"] == before["config"]

        loads: list[str] = []
        stop = _watch_row_loads(engine, loads)
        try:
            kitgum_again = _anc(session, kitgum)
        finally:
            stop()
        # Kitgum reads none of the changed rows: the same run, and no source row was loaded for it.
        assert kitgum_again["current_run_id"] == kitgum_first["current_run_id"]
        assert loads == []
        # The stamp was brought up to date, so the next request is a direct hit as well.
        assert _anc(session, kitgum)["current_run_id"] == kitgum_first["current_run_id"]

        # Acholi contains the facility, but a region reads district/city rows only (D-074).
        assert _anc(session, acholi)["current_run_id"] == acholi_first["current_run_id"]
        # Pader is the facility's district: it reads the new row, so its run is a new one.
        pader_first = _anc(session, pader)
        put_raw(session, pader_facility, "FY2024/25", "ANC1", 55)
        session.commit()
        assert _anc(session, pader)["current_run_id"] != pader_first["current_run_id"]
        assert _anc(session, acholi)["current_run_id"] == acholi_first["current_run_id"]

        # Kitgum's own source row changes: a new run, with the new value.
        put_raw(session, kitgum, "FY2024/25", "ANC1", 12_000)
        session.commit()
        kitgum_changed = _anc(session, kitgum)
        assert kitgum_changed["current_run_id"] != kitgum_first["current_run_id"]
        value = {row["indicator_code"]: row["raw_value"] for row in kitgum_changed["indicators"]}
        earlier = {row["indicator_code"]: row["raw_value"] for row in kitgum_first["indicators"]}
        assert value["ANC1_COVERAGE"] != earlier["ANC1_COVERAGE"]

        # A configuration change (here a population) always forces the full check, whatever the rows.
        config_before = _revisions(session)["config"]
        put_population(session, kitgum, 2024, 310_000, code="FAST_KITGUM_B")
        session.commit()
        assert _revisions(session)["config"] > config_before
        assert _anc(session, kitgum)["current_run_id"] != kitgum_changed["current_run_id"]
        session.close()
    finally:
        if engine is not None:
            engine.dispose()
        _cleanup(admin, monkeypatch)


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


@requires_postgres
def test_a_roll_up_is_not_read_again_for_a_change_in_another_period(monkeypatch):
    admin, test_url = _prepare_verify_db(_admin_url())
    _point_alembic(monkeypatch, test_url)
    engine = None
    try:
        command.upgrade(_alembic_cfg(), "head")
        engine = create_engine(test_url, future=True)
        session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()
        seed_reference_data(session, SEED_PASSWORD)
        programme = session.scalar(select(Programme).where(Programme.code == "MNCH"))
        map_source(session, programme.id, "ANC1", "TEST_UID_ANC1")
        pader, kitgum = _unit(session, "PADER"), _unit(session, "KITGUM")
        rows = [_month_row(session, pader, programme, month, 10) for month in FY_MONTHS]
        session.commit()

        assert ensure_period_rollups(session, ["FY2025/26"]).periods["FY2025/26"]["status"] == "rebuilt"
        session.commit()
        assert ensure_period_rollups(session, ["FY2025/26"]).periods["FY2025/26"]["status"] == "current"
        session.commit()
        state = session.get(RollupState, "FY2025/26")
        assert state is not None and state.revision is not None and str(pader.id) in state.units

        # A month outside the year changes: the revision moves, the year's inputs do not.
        _month_row(session, kitgum, programme, "202401", 7)
        session.commit()
        loads: list[str] = []
        stop = _watch_row_loads(engine, loads)
        try:
            report = ensure_period_rollups(session, ["FY2025/26"]).periods["FY2025/26"]
        finally:
            stop()
        session.commit()
        assert report["status"] == "current"
        assert loads == []

        # A month inside the year changes for one unit: that unit alone is rebuilt, never trusted.
        rows[0].is_current = False
        session.flush()
        _month_row(session, pader, programme, FY_MONTHS[0], 99)
        for month in FY_MONTHS:
            _month_row(session, kitgum, programme, month, 3)
        session.commit()
        loads = []
        stop = _watch_row_loads(engine, loads)
        try:
            report = ensure_period_rollups(session, ["FY2025/26"]).periods["FY2025/26"]
        finally:
            stop()
        session.commit()
        assert report["status"] == "rebuilt" and report["created"] == 2
        assert loads == []  # only the two changed units were read
        # The pass changed rows itself, so those units are verified by the next pass, then trusted.
        assert session.get(RollupState, "FY2025/26").revision is None
        assert ensure_period_rollups(session, ["FY2025/26"]).periods["FY2025/26"]["status"] == "current"
        session.commit()
        assert session.get(RollupState, "FY2025/26").revision is not None
        year = session.scalar(
            select(RawAggregateValue).where(
                RawAggregateValue.org_unit_id == pader.id,
                RawAggregateValue.period == "FY2025/26",
                RawAggregateValue.internal_source_key == "ANC1",
                RawAggregateValue.is_current.is_(True),
            )
        )
        assert float(year.value) == 99 + 10 * 11
        session.close()
    finally:
        if engine is not None:
            engine.dispose()
        _cleanup(admin, monkeypatch)

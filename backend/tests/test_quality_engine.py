from datetime import UTC, date, datetime

from sqlalchemy import select

from app.models import OrgUnit
from app.services.calculation import run_calculation
from app.services.mpdsr import event_display_status
from app.services.quality import scan_quality
from tests.helpers import put_event, put_population, put_raw


def test_quality_flags_cover_core_rules(session):
    uganda = session.scalar(select(OrgUnit).where(OrgUnit.code == "UG"))
    put_population(session, uganda, 2024, 10000)
    put_raw(session, uganda, "FY2024/25", "KMC_PERCENT", 110)
    put_raw(session, uganda, "FY2024/25", "RESUSCITATED", 0)
    put_raw(session, uganda, "FY2024/25", "BIRTH_ASPHYXIA", 0)
    put_raw(session, uganda, "FY2024/25", "ANC1", None, absence="no_source_row")
    run = run_calculation(
        session,
        org_unit=uganda,
        period="FY2024/25",
        user=None,
        indicator_codes=["KMC", "SUCCESSFUL_RESUSCITATION", "ANC1_COVERAGE"],
    )
    flags = scan_quality(session, org_unit=uganda, period="FY2024/25", calculation_run=run)
    codes = {flag.rule_id for flag in flags}
    assert "BOUNDED_PROPORTION_OVER_100" in codes
    assert "DENOMINATOR_ZERO" in codes
    assert "NO_DATA_VS_REPORTED_ZERO" in codes


def test_event_quality_chronology_and_active(session):
    acholi = session.scalar(select(OrgUnit).where(OrgUnit.code == "ACHOLI"))
    put_event(
        session,
        acholi,
        status="ACTIVE",
        death_date=date(2024, 7, 10),
        notification_date=date(2024, 7, 9),
        review_date=date(2024, 7, 8),
        data_values={"event_type": "perinatal_review"},
    )
    put_event(
        session,
        acholi,
        status="COMPLETED",
        death_date=date(2024, 7, 10),
        review_date=date(2024, 7, 20),
        data_values={"event_type": "perinatal_review"},
    )
    flags = scan_quality(session, org_unit=acholi, period="202407", calculation_run=None)
    codes = {flag.rule_id for flag in flags}
    assert "ACTIVE_MPDSR_WORKFLOW" in codes
    assert "NOTIFICATION_BEFORE_DEATH" in codes
    assert "REVIEW_BEFORE_DEATH" in codes or "REVIEW_INTERVAL_OUT_OF_RANGE" in codes
    assert event_display_status("ACTIVE") == "Active (not completed)"


def test_freshness_mismatch_flag(session):
    from app.models import FreshnessSnapshot

    analytics = FreshnessSnapshot(
        connector="event_analytics_query",
        source_freshness_at=datetime(2024, 7, 1, tzinfo=UTC),
        last_success_at=datetime(2024, 7, 3, tzinfo=UTC),
        status="succeeded",
    )
    tracker = FreshnessSnapshot(
        connector="tracker",
        source_freshness_at=datetime(2024, 7, 3, tzinfo=UTC),
        last_success_at=datetime(2024, 7, 3, tzinfo=UTC),
        status="succeeded",
    )
    session.add_all([analytics, tracker])
    session.flush()
    uganda = session.scalar(select(OrgUnit).where(OrgUnit.code == "UG"))
    flags = scan_quality(session, org_unit=uganda, period="202407", calculation_run=None)
    codes = {flag.rule_id for flag in flags}
    assert "STALE_ANALYTICS" in codes
    assert "SOURCE_FRESHNESS_MISMATCH" in codes

"""Amendment §6: a verified MPDSR zero versus unknown/no-data."""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select

from app.config import get_settings
from app.domain.enums import JobStatus
from app.models import CalculatedValue, Indicator, IndicatorVersion, OrgUnit
from app.services.calculation import evaluate_formula, run_calculation
from app.services.quality import scan_quality
from tests.helpers import TEST_MPDSR_PROGRAM_UID, put_event, put_mpdsr_coverage, put_raw


def _unit(session, code):
    return session.scalar(select(OrgUnit).where(OrgUnit.code == code))


def _eval(session, code, org, period="202407"):
    indicator = session.scalar(select(Indicator).where(Indicator.code == code))
    version = session.scalar(
        select(IndicatorVersion).where(
            IndicatorVersion.indicator_id == indicator.id,
            IndicatorVersion.is_current.is_(True),
        )
    )
    return evaluate_formula(session, org_unit=org, period=period, version=version, programme_id=indicator.programme_id)


def _reported(session, org, period="202407", fresh=2):
    put_raw(session, org, period, "FRESH_SB", fresh, programme_code="MPDSR")
    put_raw(session, org, period, "MACERATED_SB", 0, programme_code="MPDSR")
    put_raw(session, org, period, "NEWBORN_DEATHS", 0, programme_code="MPDSR")


def _today():
    return datetime.now(UTC).date()


def test_no_synchronisation_is_unknown_not_zero(session):
    acholi = _unit(session, "ACHOLI")
    _reported(session, acholi)
    count = _eval(session, "PERINATAL_NOTIFIED_COUNT", acholi)
    assert count.raw_value is None
    assert count.reason_code == "event_coverage_unverified"
    assert "no MPDSR Tracker synchronisation" in (count.blue_reason or "")
    coverage = _eval(session, "PERINATAL_NOTIFICATION_COVERAGE", acholi)
    assert coverage.raw_value is None
    assert coverage.status == "n_a"
    assert coverage.status != "red"


def test_complete_current_synchronisation_proves_a_legitimate_zero(session):
    acholi = _unit(session, "ACHOLI")
    _reported(session, acholi)
    put_mpdsr_coverage(session, acholi, window_start=date(2024, 7, 1), window_end=_today())
    count = _eval(session, "PERINATAL_NOTIFIED_COUNT", acholi)
    assert count.raw_value == 0
    assert count.event_coverage["status"] == "verified"
    coverage = _eval(session, "PERINATAL_NOTIFICATION_COVERAGE", acholi)
    assert coverage.raw_value == 0
    assert coverage.status == "red"


def test_partial_synchronisation_is_not_verified(session):
    acholi = _unit(session, "ACHOLI")
    put_mpdsr_coverage(
        session,
        acholi,
        window_start=date(2024, 7, 1),
        window_end=_today(),
        status=JobStatus.PARTIALLY_SUCCEEDED.value,
        rejected_count=3,
    )
    count = _eval(session, "PERINATAL_NOTIFIED_COUNT", acholi)
    assert count.raw_value is None
    assert count.event_coverage["coverage_failure"] == "incomplete"


def test_truncated_synchronisation_is_not_verified(session):
    acholi = _unit(session, "ACHOLI")
    put_mpdsr_coverage(session, acholi, window_start=date(2024, 7, 1), window_end=_today(), page_limit_reached=True)
    assert _eval(session, "PERINATAL_NOTIFIED_COUNT", acholi).raw_value is None


def test_stale_synchronisation_is_not_verified(session):
    acholi = _unit(session, "ACHOLI")
    old = datetime.now(UTC) - timedelta(hours=get_settings().dhis2_stale_hours + 2)
    put_mpdsr_coverage(session, acholi, window_start=date(2024, 7, 1), window_end=_today(), finished_at=old)
    count = _eval(session, "PERINATAL_NOTIFIED_COUNT", acholi)
    assert count.raw_value is None
    assert count.event_coverage["coverage_failure"] == "stale"


def test_window_must_reach_required_follow_up(session):
    acholi = _unit(session, "ACHOLI")
    _reported(session, acholi)
    put_mpdsr_coverage(session, acholi, window_start=date(2024, 7, 1), window_end=date(2024, 8, 1))
    completion = _eval(session, "PERINATAL_NOTIFIED_COUNT", acholi)
    assert completion.raw_value is None
    assert completion.event_coverage["coverage_failure"] == "window"
    timely = _eval(session, "PERINATAL_TIMELY_NOTIFICATION", acholi)
    assert timely.raw_value == 0
    assert timely.event_coverage["status"] == "verified"
    review = _eval(session, "PERINATAL_TIMELY_REVIEW", acholi)
    assert review.raw_value is None


def test_missing_event_mapping_is_not_verified(session):
    acholi = _unit(session, "ACHOLI")
    put_mpdsr_coverage(session, acholi, window_start=date(2024, 7, 1), window_end=_today(), with_mapping=False)
    count = _eval(session, "PERINATAL_NOTIFIED_COUNT", acholi)
    assert count.raw_value is None
    assert count.event_coverage["coverage_failure"] == "mapping"


def test_ancestor_scope_synchronisation_covers_descendants(session):
    uganda, pader = _unit(session, "UG"), _unit(session, "PADER")
    put_mpdsr_coverage(session, uganda, window_start=date(2024, 7, 1), window_end=_today())
    assert _eval(session, "PERINATAL_NOTIFIED_COUNT", pader).raw_value == 0


def test_observed_events_without_coverage_are_counted_and_flagged(session):
    acholi = _unit(session, "ACHOLI")
    _reported(session, acholi)
    event = put_event(
        session,
        acholi,
        status="COMPLETED",
        death_date=date(2024, 7, 10),
        notification_date=date(2024, 7, 10),
        data_values={"event_type": "perinatal_notification"},
    )
    run = run_calculation(
        session,
        org_unit=acholi,
        period="202407",
        user=None,
        programme_codes=["MPDSR"],
        indicator_codes=["PERINATAL_NOTIFIED_COUNT"],
    )
    value = session.scalar(select(CalculatedValue).where(CalculatedValue.calculation_run_id == run.id))
    assert value.raw_value == 1
    assert value.event_snapshot_ids == [str(event.id)]
    assert value.event_coverage["status"] == "unverified"
    flags = scan_quality(session, org_unit=acholi, period="202407", calculation_run=run)
    assert "MPDSR_EVENT_COVERAGE_UNVERIFIED" in {flag.rule_id for flag in flags if flag is not None}


def test_event_lineage_belongs_to_each_run_only(session):
    acholi = _unit(session, "ACHOLI")
    july = put_event(
        session,
        acholi,
        status="COMPLETED",
        death_date=date(2024, 7, 10),
        data_values={"event_type": "perinatal_notification"},
    )
    august = put_event(
        session,
        acholi,
        status="COMPLETED",
        death_date=date(2024, 8, 10),
        data_values={"event_type": "perinatal_notification"},
    )
    runs = {
        period: run_calculation(
            session,
            org_unit=acholi,
            period=period,
            user=None,
            programme_codes=["MPDSR"],
            indicator_codes=["PERINATAL_NOTIFIED_COUNT"],
        )
        for period in ("202407", "202408")
    }
    assert runs["202407"].config_snapshot["event_snapshot_ids"] == [str(july.id)]
    assert runs["202408"].config_snapshot["event_snapshot_ids"] == [str(august.id)]


def test_foreign_program_events_do_not_create_coverage_or_counts(session):
    acholi = _unit(session, "ACHOLI")
    put_mpdsr_coverage(session, acholi, window_start=date(2024, 7, 1), window_end=_today())
    put_event(
        session,
        acholi,
        status="COMPLETED",
        program_uid="TEST_UID_OTHER_PROGRAM",
        death_date=date(2024, 7, 10),
        data_values={"event_type": "perinatal_notification"},
    )
    put_event(
        session,
        acholi,
        status="COMPLETED",
        program_uid=TEST_MPDSR_PROGRAM_UID,
        death_date=date(2024, 7, 11),
        data_values={"event_type": "perinatal_notification"},
    )
    assert _eval(session, "PERINATAL_NOTIFIED_COUNT", acholi).raw_value == 1

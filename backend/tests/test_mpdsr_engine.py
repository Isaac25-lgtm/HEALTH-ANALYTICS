from datetime import UTC, date, datetime

from sqlalchemy import select

from app.models import Indicator, IndicatorVersion, OrgUnit
from app.services.calculation import evaluate_formula
from app.services.mpdsr import event_display_status, notification_timely, review_timely
from tests.helpers import TEST_MPDSR_PROGRAM_UID, put_event, put_mpdsr_coverage, put_raw


def _verified_coverage(session, org_unit):
    """Zero counts below are verified zeros: a complete, current sync covers July 2024."""
    return put_mpdsr_coverage(
        session,
        org_unit,
        window_start=date(2024, 7, 1),
        window_end=datetime.now(UTC).date(),
    )


def _eval(session, code, org="ACHOLI", period="202407"):
    indicator = session.scalar(select(Indicator).where(Indicator.code == code))
    version = session.scalar(
        select(IndicatorVersion).where(IndicatorVersion.indicator_id == indicator.id)
    )
    unit = session.scalar(select(OrgUnit).where(OrgUnit.code == org))
    return evaluate_formula(
        session, org_unit=unit, period=period, version=version, programme_id=indicator.programme_id
    )


def test_active_label_and_exclusion(session):
    acholi = session.scalar(select(OrgUnit).where(OrgUnit.code == "ACHOLI"))
    put_raw(session, acholi, "202407", "FRESH_SB", 1, programme_code="MPDSR")
    put_raw(session, acholi, "202407", "MACERATED_SB", 0, programme_code="MPDSR")
    put_raw(session, acholi, "202407", "NEWBORN_DEATHS", 0, programme_code="MPDSR")
    _verified_coverage(session, acholi)
    put_event(
        session,
        acholi,
        status="ACTIVE",
        program_uid=TEST_MPDSR_PROGRAM_UID,
        death_date=date(2024, 7, 10),
        notification_date=date(2024, 7, 10),
        data_values={"event_type": "perinatal_notification"},
    )
    assert event_display_status("ACTIVE") == "Active (not completed)"
    measure = _eval(session, "PERINATAL_NOTIFICATION_COVERAGE")
    assert measure.numerator == 0


def test_completed_event_included(session):
    acholi = session.scalar(select(OrgUnit).where(OrgUnit.code == "ACHOLI"))
    put_raw(session, acholi, "202407", "FRESH_SB", 1, programme_code="MPDSR")
    put_raw(session, acholi, "202407", "MACERATED_SB", 0, programme_code="MPDSR")
    put_raw(session, acholi, "202407", "NEWBORN_DEATHS", 0, programme_code="MPDSR")
    put_event(
        session,
        acholi,
        status="COMPLETED",
        death_date=date(2024, 7, 10),
        notification_date=date(2024, 7, 10),
        data_values={"event_type": "perinatal_notification"},
    )
    measure = _eval(session, "PERINATAL_NOTIFICATION_COVERAGE")
    assert measure.numerator == 1
    assert measure.raw_value == 100
    assert measure.status == "green"


def test_death_cohort_boundaries(session):
    acholi = session.scalar(select(OrgUnit).where(OrgUnit.code == "ACHOLI"))
    put_raw(session, acholi, "202407", "FRESH_SB", 1, programme_code="MPDSR")
    _verified_coverage(session, acholi)
    put_event(
        session,
        acholi,
        status="COMPLETED",
        program_uid=TEST_MPDSR_PROGRAM_UID,
        death_date=date(2024, 6, 30),
        data_values={"event_type": "perinatal_notification"},
    )
    assert _eval(session, "PERINATAL_NOTIFICATION_COVERAGE").numerator == 0


def test_notification_same_and_next_day(session):
    assert notification_timely(date(2024, 7, 1), date(2024, 7, 1))
    assert notification_timely(date(2024, 7, 1), date(2024, 7, 2))
    assert not notification_timely(date(2024, 7, 1), date(2024, 7, 3))


def test_review_day_0_7_and_8(session):
    assert review_timely(date(2024, 7, 1), date(2024, 7, 1))
    assert review_timely(date(2024, 7, 1), date(2024, 7, 8))
    assert not review_timely(date(2024, 7, 1), date(2024, 7, 9))


def test_notification_before_death_excluded_from_timely(session):
    acholi = session.scalar(select(OrgUnit).where(OrgUnit.code == "ACHOLI"))
    put_raw(session, acholi, "202407", "FRESH_SB", 1, programme_code="MPDSR")
    _verified_coverage(session, acholi)
    put_event(
        session,
        acholi,
        status="COMPLETED",
        program_uid=TEST_MPDSR_PROGRAM_UID,
        death_date=date(2024, 7, 10),
        notification_date=date(2024, 7, 9),
        data_values={"event_type": "perinatal_notification"},
    )
    measure = _eval(session, "PERINATAL_TIMELY_NOTIFICATION")
    assert measure.numerator == 0


def test_linelist_gt_aggregate_is_blue(session):
    acholi = session.scalar(select(OrgUnit).where(OrgUnit.code == "ACHOLI"))
    put_raw(session, acholi, "202407", "FRESH_SB", 1, programme_code="MPDSR")
    put_raw(session, acholi, "202407", "MACERATED_SB", 0, programme_code="MPDSR")
    put_raw(session, acholi, "202407", "NEWBORN_DEATHS", 0, programme_code="MPDSR")
    put_event(
        session,
        acholi,
        status="COMPLETED",
        death_date=date(2024, 7, 10),
        data_values={"event_type": "perinatal_notification"},
    )
    put_event(
        session,
        acholi,
        status="COMPLETED",
        death_date=date(2024, 7, 11),
        data_values={"event_type": "perinatal_notification"},
    )
    measure = _eval(session, "PERINATAL_NOTIFICATION_COVERAGE")
    assert measure.numerator == 2
    assert measure.denominator == 1
    assert measure.status == "blue"


def test_maternal_thresholds_differ(session):
    acholi = session.scalar(select(OrgUnit).where(OrgUnit.code == "ACHOLI"))
    put_raw(session, acholi, "202407", "MATERNAL_DEATHS", 2, programme_code="MPDSR")
    put_event(
        session,
        acholi,
        status="COMPLETED",
        death_date=date(2024, 7, 10),
        data_values={"event_type": "maternal_notification"},
    )
    measure = _eval(session, "MATERNAL_NOTIFICATION_COVERAGE")
    assert measure.raw_value == 50
    assert measure.status == "red"

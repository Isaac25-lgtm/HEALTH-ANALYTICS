from sqlalchemy import select

from app.models import OrgUnit, User
from app.services.modules import evaluate_module
from tests.conftest import auth_header, login, query_module
from tests.helpers import put_population, put_raw


def _unit(session, code):
    return session.scalar(select(OrgUnit).where(OrgUnit.code == code))


def _user(session, username):
    return session.scalar(select(User).where(User.username == username))


def _load_anc_verified_sources(session, org, period, year, source):
    put_population(session, org, year, source["population"], code=f"FIXTURE_POP_{year}")
    for key, value in source.items():
        if key == "population":
            continue
        put_raw(session, org, period, key, value)


def test_anc_appendix_t_fixture_and_percentage_point_change(session):
    acholi = _unit(session, "ACHOLI")
    admin = _user(session, "admin.user")
    _load_anc_verified_sources(
        session,
        acholi,
        "FY2024/25",
        2024,
        {
            "population": 1_000_000,
            "ANC1": 48700,
            "ANC1_FT": 18846.9,
            "ANC4": 29650,
            "ANC8": 4250,
            "IPT3": 32150,
            "HB_TESTED": 16071,
            "IFA_30": 41054.1,
            "ULTRASOUND": 13587.3,
            "ANC1_AGE_LT15": 0,
            "ANC1_AGE_15_19": 9642.6,
        },
    )
    _load_anc_verified_sources(
        session,
        acholi,
        "FY2025/26",
        2025,
        {
            "population": 1_000_000,
            "ANC1": 47700,
            "ANC1_FT": 19747.8,
            "ANC4": 29150,
            "ANC8": 5850,
            "IPT3": 31600,
            "HB_TESTED": 17124.3,
            "IFA_30": 86480.1,
            "ULTRASOUND": 16933.5,
            "ANC1_AGE_LT15": 0,
            "ANC1_AGE_15_19": 9158.4,
        },
    )
    result = evaluate_module(
        session,
        user=admin,
        org_unit_id=acholi.id,
        period="FY2025/26",
        module="anc",
        comparison_period="FY2024/25",
        include_children=False,
    )
    by_code = {row["indicator_code"]: row for row in result["indicators"]}
    assert round(by_code["ANC1_COVERAGE"]["raw_value"], 1) == 95.4
    assert by_code["ANC1_COVERAGE"]["status"] == "green"
    assert by_code["IFA_COVERAGE"]["raw_value"] > 100
    assert by_code["IFA_COVERAGE"]["raw_value"] != 100
    assert by_code["TEENAGE_PREGNANCY"]["status"] == "red"
    change = by_code["ANC1_COVERAGE"]["change"]
    assert change["change_kind"] == "percentage_point"
    assert round(change["percentage_point_change"], 1) == -2.0
    assert change["relative_percent_change"] is not None
    assert result["programme"] == "MNCH"


def test_missing_population_disables_only_population_derived_anc(session):
    acholi = _unit(session, "ACHOLI")
    admin = _user(session, "admin.user")
    put_raw(session, acholi, "FY2024/25", "ANC1", 100)
    put_raw(session, acholi, "FY2024/25", "ANC1_FT", 40)
    put_raw(session, acholi, "FY2024/25", "HB_TESTED", 30)
    result = evaluate_module(
        session,
        user=admin,
        org_unit_id=acholi.id,
        period="FY2024/25",
        module="anc",
        include_children=False,
    )
    by_code = {row["indicator_code"]: row for row in result["indicators"]}
    assert by_code["ANC1_COVERAGE"]["raw_value"] is None
    assert by_code["ANC1_FIRST_TRIMESTER"]["raw_value"] == 40
    assert by_code["HB_TESTING"]["raw_value"] == 30


def test_intrapartum_units_and_appendix_t_states(session):
    acholi = _unit(session, "ACHOLI")
    admin = _user(session, "admin.user")
    put_population(session, acholi, 2024, 1_000_000, code="FIX_IP_2024")
    put_population(session, acholi, 2025, 1_000_000, code="FIX_IP_2025")
    deliveries = 1_000_000 * 0.0485 * 0.714
    put_raw(session, acholi, "FY2024/25", "DELIVERIES", deliveries)
    put_raw(session, acholi, "FY2024/25", "CS", 0.099 * deliveries)
    put_raw(session, acholi, "FY2024/25", "KMC_PERCENT", 78.2)
    put_raw(session, acholi, "FY2024/25", "RESUSCITATED", 101.9)
    put_raw(session, acholi, "FY2024/25", "BIRTH_ASPHYXIA", 100)
    put_raw(session, acholi, "FY2024/25", "FRESH_SB", 0.0057 * deliveries)
    put_raw(session, acholi, "FY2024/25", "MACERATED_SB", 0)
    put_raw(session, acholi, "FY2024/25", "NEWBORN_DEATHS", 0.0087 * deliveries)
    put_raw(session, acholi, "FY2024/25", "LIVE_BIRTHS", deliveries)
    put_raw(session, acholi, "FY2024/25", "MATERNAL_DEATHS", 0.000985 * deliveries)
    result = evaluate_module(
        session,
        user=admin,
        org_unit_id=acholi.id,
        period="FY2024/25",
        module="intrapartum",
        include_children=False,
    )
    by_code = {row["indicator_code"]: row for row in result["indicators"]}
    assert by_code["INSTITUTIONAL_DELIVERY"]["unit"] == "%"
    assert by_code["PMR"]["unit"] != "%"
    assert "1,000" in (by_code["PMR"]["unit"] or "") or by_code["PMR"]["unit"] in {"/1000", "per_1000", "1/1000"}
    assert by_code["CAESAREAN_SECTION"]["status"] == "green"
    assert by_code["KMC"]["status"] == "yellow"
    put_raw(session, acholi, "FY2024/25", "KMC_PERCENT", 101.9)
    put_raw(session, acholi, "FY2024/25", "RESUSCITATED", 121.8)
    again = evaluate_module(
        session,
        user=admin,
        org_unit_id=acholi.id,
        period="FY2024/25",
        module="intrapartum",
        include_children=False,
    )
    by_code = {row["indicator_code"]: row for row in again["indicators"]}
    assert by_code["KMC"]["status"] == "blue"
    assert by_code["SUCCESSFUL_RESUSCITATION"]["status"] == "blue"


def test_immunization_unclassified_dropout_and_continuum(session):
    uganda = _unit(session, "UG")
    admin = _user(session, "admin.user")
    put_population(session, uganda, 2024, 1_000_000, code="FIX_EPI")
    put_raw(session, uganda, "FY2024/25", "PENTA1", 43000)
    put_raw(session, uganda, "FY2024/25", "PENTA3", 40000)
    put_raw(session, uganda, "FY2024/25", "MV1", 43000)
    put_raw(session, uganda, "FY2024/25", "MV4", 34400)
    result = evaluate_module(
        session,
        user=admin,
        org_unit_id=uganda.id,
        period="FY2024/25",
        module="immunization",
        include_children=False,
    )
    by_code = {row["indicator_code"]: row for row in result["indicators"]}
    assert by_code["MV4_COVERAGE"]["status"] in {"n_a", "unclassified", None} or by_code[
        "MV4_COVERAGE"
    ]["performance_status"] in {"n_a", "unclassified"}
    assert by_code["PENTA_DROPOUT"]["raw_value"] is not None
    assert result["continuum"]["penta_dropout"]["threshold_state"] == "no_approved_threshold"
    assert result["continuum"]["malaria_dropout"]["threshold_state"] == "no_approved_threshold"


def test_mpdsr_includes_both_streams_and_hides_event_uids(session):
    acholi = _unit(session, "ACHOLI")
    admin = _user(session, "admin.user")
    put_raw(session, acholi, "FY2024/25", "FRESH_SB", 2, programme_code="MPDSR")
    put_raw(session, acholi, "FY2024/25", "MACERATED_SB", 0, programme_code="MPDSR")
    put_raw(session, acholi, "FY2024/25", "NEWBORN_DEATHS", 0, programme_code="MPDSR")
    put_raw(session, acholi, "FY2024/25", "MATERNAL_DEATHS", 1, programme_code="MPDSR")
    result = evaluate_module(
        session,
        user=admin,
        org_unit_id=acholi.id,
        period="FY2024/25",
        module="mpdsr",
        include_children=False,
    )
    codes = {row["indicator_code"] for row in result["indicators"]}
    assert "PERINATAL_REPORTED_DEATHS" in codes
    assert "MATERNAL_REPORTED_DEATHS" in codes
    serialized = str(result)
    assert "TEST_UID_" not in serialized or "event" not in serialized.lower()
    assert "event_uid" not in serialized


def test_mnch_only_cannot_open_immunization_or_mpdsr_module(client, session):
    uganda = _unit(session, "UG")
    token = login(client, "mnch.only")
    denied_epi = query_module(client, auth_header(token), "immunization", uganda.id)
    denied_mpdsr = query_module(client, auth_header(token), "mpdsr", uganda.id)
    assert denied_epi.status_code == 403
    assert denied_mpdsr.status_code == 403


def test_geography_restriction_on_module(client, session):
    teso = _unit(session, "TESO")
    token = login(client, "acholi.analyst")
    response = query_module(client, auth_header(token), "anc", teso.id)
    assert response.status_code == 403

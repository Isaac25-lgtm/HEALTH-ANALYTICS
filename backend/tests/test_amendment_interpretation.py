"""Amendment §9: direction-aware change interpretation, findings and rankings."""

import pytest
from sqlalchemy import select

from app.domain.indicator_catalog import EPI_VACCINE_COVERAGE_CODES
from app.domain.interpretation import UNSAFE_RANK_CODES, interpret_change, rank_units
from app.domain.modules import MODULE_INDICATORS
from app.models import OrgUnit, User
from app.services.ai_gateway import _findings
from app.services.modules import evaluate_module
from tests.conftest import auth_header, login, query_dashboard
from tests.helpers import put_raw


def _value(raw, status="green", quality=None):
    return {"raw_value": raw, "status": status, "quality_status": quality}


@pytest.mark.parametrize("mode", ["higher_is_better", "bounded_higher", "maternal_coverage"])
def test_higher_modes_treat_increase_as_improvement(mode):
    up = interpret_change(classification_mode=mode, current=_value(80), previous=_value(70))
    down = interpret_change(classification_mode=mode, current=_value(60), previous=_value(70))
    assert up["interpretation"] == "improved"
    assert down["interpretation"] == "deteriorated"


@pytest.mark.parametrize("mode", ["lower_is_better", "teenage_pregnancy", "mmr"])
def test_lower_modes_treat_decrease_as_improvement(mode):
    down = interpret_change(classification_mode=mode, current=_value(10), previous=_value(20))
    up = interpret_change(classification_mode=mode, current=_value(30), previous=_value(20))
    assert down["interpretation"] == "improved"
    assert up["interpretation"] == "deteriorated"


def test_desired_range_uses_distance_from_the_range():
    band = [5.0, 15.0]

    def ranged(now, before):
        return interpret_change(
            classification_mode="desired_range", current=_value(now), previous=_value(before), desired_range=band
        )

    toward, away, inside, overshoot = ranged(18, 25), ranged(2, 4), ranged(6, 14), ranged(26, 3)
    assert toward["interpretation"] == "improved"
    assert away["interpretation"] == "deteriorated"
    assert inside["interpretation"] == "unchanged"
    assert overshoot["interpretation"] == "deteriorated"
    unconfigured = interpret_change(classification_mode="desired_range", current=_value(6), previous=_value(3))
    assert unconfigured["interpretation"] == "not_interpreted"


@pytest.mark.parametrize("mode", ["unclassified", "neutral_count", None, "unknown_mode"])
def test_unclassified_and_count_changes_are_not_interpreted(mode):
    result = interpret_change(classification_mode=mode, current=_value(80, "n_a"), previous=_value(70, "n_a"))
    assert result["interpretation"] == "not_interpreted"
    assert "numeric change" in result["reason"]


def test_blue_and_missing_values_are_never_interpreted():
    blue_now = interpret_change(
        classification_mode="higher_is_better", current=_value(120, "blue"), previous=_value(70)
    )
    blue_quality = interpret_change(
        classification_mode="higher_is_better", current=_value(90, "green", "blue"), previous=_value(70)
    )
    blue_before = interpret_change(
        classification_mode="lower_is_better", current=_value(5), previous=_value(40, "blue")
    )
    missing = interpret_change(classification_mode="higher_is_better", current=_value(None, "n_a"), previous=_value(70))
    absent = interpret_change(classification_mode="higher_is_better", current=_value(70), previous=None)
    for result in (blue_now, blue_quality, blue_before):
        assert result["interpretation"] == "not_interpreted"
        assert "BLUE" in result["reason"]
    for result in (missing, absent):
        assert result["interpretation"] == "not_interpreted"
        assert "missing" in result["reason"]


def test_change_within_display_precision_is_unchanged():
    result = interpret_change(
        classification_mode="higher_is_better", current=_value(95.04), previous=_value(95.01), precision=1
    )
    assert result["interpretation"] == "unchanged"
    assert result["status_transition"] == ["green", "green"]


def _row(name, raw, status="green", quality=None, code="IND"):
    return {
        "org_unit_id": f"id-{name}",
        "org_unit_name": name,
        "values": {code: {"raw_value": raw, "status": status, "quality_status": quality}},
    }


def test_higher_is_better_ranking_puts_highest_first_and_separates_exclusions():
    rows = [
        _row("Alpha", 60, "red"),
        _row("Bravo", 90),
        _row("Charlie", 130, "blue"),
        _row("Delta", None, "n_a"),
        _row("Echo", 75, "yellow"),
        _row("Foxtrot", 50, "n_a"),
        _row("Golf", 88, "green", "blue"),
    ]
    ranking = rank_units(rows, indicator_code="IND", classification_mode="higher_is_better")
    assert ranking["ranking_allowed"] is True
    assert ranking["order_rule"] == "higher_values_rank_first"
    assert [item["org_unit_name"] for item in ranking["best"]] == ["Bravo", "Echo", "Alpha"]
    assert [item["org_unit_name"] for item in ranking["worst"]] == ["Alpha", "Echo", "Bravo"]
    assert {item["org_unit_name"] for item in ranking["excluded"]["blue"]} == {"Charlie", "Golf"}
    assert [item["org_unit_name"] for item in ranking["excluded"]["missing"]] == ["Delta"]
    assert [item["org_unit_name"] for item in ranking["excluded"]["non_assessable"]] == ["Foxtrot"]
    assert ranking["ordered_org_unit_ids"] == ["id-Bravo", "id-Echo", "id-Alpha"]


@pytest.mark.parametrize("mode", ["lower_is_better", "teenage_pregnancy"])
def test_lower_is_better_ranking_puts_lowest_first(mode):
    rows = [_row("Alpha", 20, "red"), _row("Bravo", 4), _row("Charlie", 9, "yellow")]
    ranking = rank_units(rows, indicator_code="IND", classification_mode=mode)
    assert ranking["order_rule"] == "lower_values_rank_first"
    assert [item["org_unit_name"] for item in ranking["best"]] == ["Bravo", "Charlie", "Alpha"]
    assert ranking["worst"][0]["org_unit_name"] == "Alpha"


def test_desired_range_ranking_orders_by_distance_with_deterministic_ties():
    rows = [
        _row("Alpha", 25, "red"),
        _row("Bravo", 10),
        _row("Charlie", 2, "red"),
        _row("Delta", 12),
        _row("Echo", 18, "yellow"),
    ]
    ranking = rank_units(rows, indicator_code="IND", classification_mode="desired_range", desired_range=[5.0, 15.0])
    assert ranking["order_rule"] == "closest_to_desired_range_ranks_first"
    assert [item["org_unit_name"] for item in ranking["best"]] == ["Bravo", "Delta", "Charlie", "Echo", "Alpha"]


@pytest.mark.parametrize("mode", ["unclassified", "neutral_count", None])
def test_unclassified_indicators_are_not_ranked(mode):
    ranking = rank_units([_row("Alpha", 10, "n_a")], indicator_code="IND", classification_mode=mode)
    assert ranking["ranking_allowed"] is False
    assert ranking["reason_code"] == "no_approved_ranking_rule"
    assert ranking["best"] == [] and ranking["worst"] == []


def test_desired_range_without_a_configured_range_is_not_ranked():
    ranking = rank_units([_row("Alpha", 10)], indicator_code="IND", classification_mode="desired_range")
    assert ranking["ranking_allowed"] is False


@pytest.mark.parametrize("code", ["PMR", "MMR", "FRESH_STILLBIRTH_RATE", *MODULE_INDICATORS["mpdsr"]])
def test_small_count_mortality_and_mpdsr_indicators_are_not_ranked(code):
    assert code in UNSAFE_RANK_CODES
    ranking = rank_units([_row("Alpha", 1, code=code)], indicator_code=code, classification_mode="lower_is_better")
    assert ranking["ranking_allowed"] is False
    assert ranking["reason_code"] == "unsafe_small_count_indicator"


def _package(**change):
    return {
        "current_run_id": "run",
        "indicators": [
            {
                "indicator_code": "TEENAGE_PREGNANCY",
                "name": "Teenage pregnancy",
                "raw_value": 10.0,
                "status": "yellow",
                "unit": "%",
                "change": {"percentage_point_change": -10.0, **change},
                "calculation_run_id": "run",
            }
        ],
    }


def test_findings_follow_interpretation_not_the_sign_of_the_change():
    improved = _findings(_package(interpretation="improved"))
    assert any("improved" in item["title"] for item in improved)
    assert not any("deteriorated" in item["title"] for item in improved)
    silent = _findings(_package(interpretation="not_interpreted"))
    assert not any("improved" in item["title"] or "deteriorated" in item["title"] for item in silent)


def test_blue_and_missing_values_become_data_quality_findings():
    package = {
        "current_run_id": "run",
        "indicators": [
            {"indicator_code": "KMC", "name": "KMC", "raw_value": 120.0, "status": "blue", "change": {}},
            {"indicator_code": "ANC4", "name": "ANC4", "raw_value": None, "status": "n_a", "change": {}},
        ],
    }
    kinds = {item["indicator_code"]: item["kind"] for item in _findings(package)}
    assert kinds == {"KMC": "data_quality", "ANC4": "data_quality"}


def test_module_change_uses_the_indicator_direction(session):
    acholi = session.scalar(select(OrgUnit).where(OrgUnit.code == "ACHOLI"))
    admin = session.scalar(select(User).where(User.username == "admin.user"))
    for period, first_trimester, teenage in (("FY2023/24", 4_000, 2_000), ("FY2024/25", 3_000, 1_000)):
        put_raw(session, acholi, period, "ANC1", 10_000)
        put_raw(session, acholi, period, "ANC1_FT", first_trimester)
        put_raw(session, acholi, period, "ANC1_AGE_LT15", 0)
        put_raw(session, acholi, period, "ANC1_AGE_15_19", teenage)
    result = evaluate_module(
        session, user=admin, org_unit_id=acholi.id, period="FY2024/25", module="anc", include_children=False
    )
    by_code = {row["indicator_code"]: row for row in result["indicators"]}
    assert by_code["TEENAGE_PREGNANCY"]["change"]["percentage_point_change"] == pytest.approx(-10.0)
    assert by_code["TEENAGE_PREGNANCY"]["change"]["interpretation"] == "improved"
    assert by_code["ANC1_FIRST_TRIMESTER"]["change"]["percentage_point_change"] == pytest.approx(-10.0)
    assert by_code["ANC1_FIRST_TRIMESTER"]["change"]["interpretation"] == "deteriorated"


def test_dashboard_ranks_lower_is_better_children_lowest_first(client, session):
    acholi = session.scalar(select(OrgUnit).where(OrgUnit.code == "ACHOLI"))
    pader = session.scalar(select(OrgUnit).where(OrgUnit.code == "PADER"))
    kitgum = session.scalar(select(OrgUnit).where(OrgUnit.code == "KITGUM"))
    for unit, teenage in ((pader, 1_000), (kitgum, 2_000)):
        put_raw(session, unit, "FY2024/25", "ANC1", 10_000)
        put_raw(session, unit, "FY2024/25", "ANC1_AGE_LT15", 0)
        put_raw(session, unit, "FY2024/25", "ANC1_AGE_15_19", teenage)
    session.commit()
    headers = auth_header(login(client, "acholi.analyst"))
    response = query_dashboard(client, headers, acholi.id, selected_indicator="TEENAGE_PREGNANCY")
    assert response.status_code == 201, response.text
    ranking = response.json()["ranking"]
    assert ranking["ranking_allowed"] is True
    assert ranking["order_rule"] == "lower_values_rank_first"
    assert [item["org_unit_code"] for item in ranking["best"]] == ["PADER", "KITGUM"]
    assert ranking["worst"][0]["org_unit_code"] == "KITGUM"


def test_dashboard_ranks_immunization_only_under_the_approved_epi_bands(client, session):
    # Immunisation coverage was unranked until the owner approved the EPI bands (v2-epi-bands,
    # 2026-09-24); ranking now follows that rule and nothing else.
    uganda = session.scalar(select(OrgUnit).where(OrgUnit.code == "UG"))
    headers = auth_header(login(client, "national.analyst"))
    response = query_dashboard(client, headers, uganda.id, module="immunization")
    assert response.status_code == 201, response.text
    ranking = response.json()["ranking"]
    assert ranking["indicator_code"] in EPI_VACCINE_COVERAGE_CODES
    assert ranking["classification_mode"] == "higher_is_better"
    assert ranking["ranking_allowed"] is True
    assert ranking["order_rule"] == "higher_values_rank_first"

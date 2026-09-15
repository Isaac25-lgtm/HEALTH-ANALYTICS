"""Amendment §10: MPDSR cause patterns are governed, suppressed and never facility-attributable."""

from datetime import date

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.domain import mpdsr_cause_taxonomy
from app.domain.mpdsr_cause_taxonomy import CauseTaxonomy
from app.models import OrgUnit, User
from app.services.evidence import redact
from app.services.modules import evaluate_module
from tests.helpers import put_event

# Synthetic taxonomy for these presentation tests only; production has none configured.
TEST_TAXONOMY = CauseTaxonomy(
    version="test-only",
    approval_reference="synthetic test fixture, not an approved taxonomy",
    labels={"OBST_HAEM": "Obstetric haemorrhage", "SEPSIS": "Sepsis", "ECLAMPSIA": "Eclampsia"},
)


@pytest.fixture(autouse=True)
def _test_taxonomy(monkeypatch):
    monkeypatch.setattr(mpdsr_cause_taxonomy, "APPROVED_CAUSE_TAXONOMY", TEST_TAXONOMY)


def _unit(session, code):
    return session.scalar(select(OrgUnit).where(OrgUnit.code == code))


def _user(session, username):
    return session.scalar(select(User).where(User.username == username))


def _event(session, unit, causes, **extra):
    return put_event(
        session,
        unit,
        death_date=date(2024, 9, 1),
        notification_date=date(2024, 9, 2),
        data_values={"event_type": "maternal_notification", "structured_cause_mentions": causes, **extra},
    )


def _seed_causes(session):
    pader, kitgum = _unit(session, "PADER"), _unit(session, "KITGUM")
    _event(session, pader, ["OBST_HAEM", "SEPSIS"], cause="free text naming a ward")
    _event(session, kitgum, ["OBST_HAEM"])
    _event(session, pader, ["SEPSIS"])
    _event(session, pader, ["ECLAMPSIA"])


def _mpdsr(session, username, code):
    result = evaluate_module(
        session,
        user=_user(session, username),
        org_unit_id=_unit(session, code).id,
        period="FY2024/25",
        module="mpdsr",
        include_children=False,
    )
    return result["mpdsr"]


def test_causes_are_withheld_without_an_approved_suppression_rule(session, monkeypatch):
    monkeypatch.setattr(get_settings(), "mpdsr_cause_min_cell_count", None)
    _seed_causes(session)
    extras = _mpdsr(session, "mpdsr.analyst", "ACHOLI")
    assert extras["structured_cause_mentions"] == []
    assert extras["cause_disclosure"]["status"] == "withheld"
    assert "suppression" in extras["cause_disclosure"]["reason"]


def test_causes_are_withheld_below_regional_level(session, monkeypatch):
    monkeypatch.setattr(get_settings(), "mpdsr_cause_min_cell_count", 1)
    _seed_causes(session)
    admin = _mpdsr(session, "admin.user", "PADER")
    assert admin["structured_cause_mentions"] == []
    assert admin["cause_disclosure"]["status"] == "withheld"
    assert "below regional level" in admin["cause_disclosure"]["reason"]


def test_causes_require_mpdsr_event_permission(session, monkeypatch):
    monkeypatch.setattr(get_settings(), "mpdsr_cause_min_cell_count", 1)
    _seed_causes(session)
    extras = _mpdsr(session, "acholi.analyst", "ACHOLI")
    assert extras["structured_cause_mentions"] == []
    assert extras["cause_disclosure"]["status"] == "withheld"
    assert extras["active_events"] is None


def test_disclosed_causes_suppress_small_cells_and_single_reporting_units(session, monkeypatch):
    monkeypatch.setattr(get_settings(), "mpdsr_cause_min_cell_count", 2)
    _seed_causes(session)
    extras = _mpdsr(session, "mpdsr.analyst", "ACHOLI")
    assert extras["cause_disclosure"]["status"] == "disclosed"
    assert extras["structured_cause_mentions"] == [
        {"code": "OBST_HAEM", "category": "Obstetric haemorrhage", "mentions": 2}
    ]
    assert extras["cause_disclosure"]["taxonomy_version"] == "test-only"
    # Sepsis meets the cell count but comes from one district only; Eclampsia is below it.
    assert extras["cause_disclosure"]["suppressed_categories"] == 2
    encoded = str(extras)
    assert "Sepsis" not in encoded and "SEPSIS" not in encoded
    assert "Eclampsia" not in encoded and "ECLAMPSIA" not in encoded
    assert "free text naming a ward" not in encoded
    for item in extras["structured_cause_mentions"]:
        assert set(item) == {"code", "category", "mentions"}
        assert isinstance(item["mentions"], int)


def test_free_text_cause_fields_are_never_counted(session, monkeypatch):
    monkeypatch.setattr(get_settings(), "mpdsr_cause_min_cell_count", 1)
    pader, kitgum = _unit(session, "PADER"), _unit(session, "KITGUM")
    for unit in (pader, kitgum):
        put_event(
            session,
            unit,
            death_date=date(2024, 9, 1),
            data_values={"event_type": "maternal_notification", "cause": "haemorrhage", "narrative": "details"},
        )
    extras = _mpdsr(session, "mpdsr.analyst", "ACHOLI")
    assert extras["structured_cause_mentions"] == []


def test_causes_are_withheld_while_no_taxonomy_is_approved(session, monkeypatch):
    monkeypatch.setattr(mpdsr_cause_taxonomy, "APPROVED_CAUSE_TAXONOMY", None)
    monkeypatch.setattr(get_settings(), "mpdsr_cause_min_cell_count", 1)
    _seed_causes(session)
    extras = _mpdsr(session, "mpdsr.analyst", "ACHOLI")
    assert extras["structured_cause_mentions"] == []
    assert extras["cause_disclosure"]["status"] == "withheld"
    assert "taxonomy" in extras["cause_disclosure"]["reason"]


def test_labels_or_free_text_under_the_structured_field_are_never_matched(session, monkeypatch):
    monkeypatch.setattr(get_settings(), "mpdsr_cause_min_cell_count", 1)
    pader, kitgum = _unit(session, "PADER"), _unit(session, "KITGUM")
    for unit in (pader, kitgum):
        _event(session, unit, ["Obstetric haemorrhage", "obst_haem", "haemorrhage after delivery at home"])
        put_event(
            session,
            unit,
            death_date=date(2024, 9, 1),
            data_values={"event_type": "maternal_notification", "cause_mentions": ["OBST_HAEM"]},
        )
    extras = _mpdsr(session, "mpdsr.analyst", "ACHOLI")
    assert extras["cause_disclosure"]["status"] == "disclosed"
    assert extras["structured_cause_mentions"] == []


def test_redaction_is_recursive():
    payload = {
        "summary": {"mentions": 3, "patient_name": "remove", "rows": [{"narrative": "remove", "category": "keep"}]},
        "events": [{"event_uid": "TEST_UID_EVENT1", "nested": {"mother_name": "remove", "count": 1}}],
    }
    cleaned = redact(payload)
    encoded = str(cleaned)
    assert "remove" not in encoded
    assert "TEST_UID_EVENT1" not in encoded
    assert cleaned["summary"]["rows"][0]["category"] == "keep"
    assert cleaned["events"][0]["nested"]["count"] == 1

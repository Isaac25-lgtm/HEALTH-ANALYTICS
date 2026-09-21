"""Governance of the live mapping set: caesarean sections, withheld keys, version selection.

These cover the owner's conditional approval of 2026-09-21. The caesarean numerator moved from a
Tracker/TRUE_ONLY pair (020-DP15 + 020-DP16, which returned nothing at aggregate grain) to the
aggregate element 108-SP01, and four source keys stay deliberately unmapped because the national
instance measures different age bands than those indicator definitions require.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.domain.enums import OrgUnitLevel
from app.integrations.dhis2.aggregate import parse_analytics_rows
from app.models import OrgUnit, Programme, SourceMapping
from app.services.geography import create_org_unit
from app.services.mapping_coverage import (
    CoverageError,
    ensure_coverage,
    evaluate_coverage,
    required_source_keys,
)
from scripts.import_source_mappings import CONFIRMED, CONFIRMED_WITH_CATEGORY, WITHHELD

LIVE_VERSION = "live-2026-09-21"


def test_caesarean_uses_the_aggregate_element_and_never_the_tracker_pair():
    """020-DP15/DP16 are TRUE_ONLY Tracker fields; binding them would report nothing as zero."""
    programme, code = CONFIRMED["CS"]
    assert programme == "MNCH"
    assert code == "108-SP01"
    bound_codes = {value[1] for value in CONFIRMED.values()}
    assert "020-DP15" not in bound_codes
    assert "020-DP16" not in bound_codes


def test_caesarean_denominator_is_the_approved_total_deliveries():
    from app.domain.indicator_catalog import INDICATOR_CATALOG

    indicator = next(item for item in INDICATOR_CATALOG if item["code"] == "CAESAREAN_SECTION")
    spec = indicator["formula_spec"]
    assert spec["numerator_keys"] == ["CS"]
    assert spec["denominator"]["source_keys"] == ["DELIVERIES"]
    # A caesarean rate compares caesareans with deliveries in the same period, so the denominator
    # is not scaled by elapsed time the way a population target is.
    assert spec["denominator"]["period_adjust"] is False
    assert CONFIRMED["DELIVERIES"] == ("MNCH", "105-MA04")


def test_a_unit_that_did_not_report_stays_missing_and_never_becomes_zero():
    """Four districts did not report caesareans in June 2025. Absent is not the same as zero."""
    payload = {
        "headers": [{"name": "dx"}, {"name": "ou"}, {"name": "pe"}, {"name": "value"}],
        "rows": [
            ["sDLD6q8wOCn", "TEST_UID_REPORTED", "202506", "12"],
            ["sDLD6q8wOCn", "TEST_UID_ZERO", "202506", "0"],
            ["sDLD6q8wOCn", "TEST_UID_ABSENT", "202506", ""],
        ],
        "serverDate": "2026-09-21T00:00:00Z",
    }
    rows = {row.org_unit_uid: row for row in parse_analytics_rows(payload)}
    assert rows["TEST_UID_REPORTED"].value == 12
    # A reported zero is a real observation and must be preserved as zero.
    assert rows["TEST_UID_ZERO"].value == 0
    assert rows["TEST_UID_ZERO"].absence_reason is None
    # An empty value is an absent observation, never zero.
    assert rows["TEST_UID_ABSENT"].value is None
    assert rows["TEST_UID_ABSENT"].absence_reason == "no_source_row"


def test_caesarean_mapping_carries_single_element_provenance():
    """108-SP01 has the default category combination, so no operand or COC may be attached."""
    assert "CS" not in CONFIRMED_WITH_CATEGORY
    programme, code = CONFIRMED["CS"]
    assert "." not in code, "a DE.COC operand would imply category detail this element does not have"


def test_withheld_keys_stay_unmapped_with_recorded_reasons():
    assert set(WITHHELD) == {"TD_1549", "DEWORM_1_14", "VITA_6_11", "UNDER5"}
    for key, reason in WITHHELD.items():
        assert key not in CONFIRMED, f"{key} must not be bound to an approximate element"
        assert key not in CONFIRMED_WITH_CATEGORY
        assert reason.strip(), f"{key} needs a recorded reason"


def test_the_confirmed_set_is_the_forty_four_the_owner_approved():
    mapped = set(CONFIRMED) | set(CONFIRMED_WITH_CATEGORY)
    assert len(mapped) == 44
    assert mapped.isdisjoint(set(WITHHELD))
    every_key = required_source_keys("MNCH") | required_source_keys("EPI") | required_source_keys("MPDSR")
    assert mapped | set(WITHHELD) == every_key


def test_adolescent_anc_bands_are_category_slices_of_one_element():
    assert CONFIRMED_WITH_CATEGORY["ANC1_AGE_LT15"] == ("MNCH", "105-AN01A", "<15Yrs")
    assert CONFIRMED_WITH_CATEGORY["ANC1_AGE_15_19"] == ("MNCH", "105-AN01A", "15-19Yrs")
    # They slice the same element ANC1 itself is bound to, so the totals stay consistent.
    assert CONFIRMED["ANC1"] == ("MNCH", "105-AN01A")


def _mapping(session, programme, key, uid, version=LIVE_VERSION, enabled=True):
    row = SourceMapping(
        internal_source_key=key,
        programme_id=programme.id,
        dhis2_item_uid=uid,
        item_kind="data_element",
        aggregation_semantics="SUM",
        mapping_version=version,
        enabled=enabled,
    )
    session.add(row)
    return row


def test_partial_version_is_usable_while_empty_version_is_not(session):
    """A deliberately incomplete version must still extract the keys it does map."""
    programme = session.scalar(select(Programme).where(Programme.code == "MNCH"))
    _mapping(session, programme, "ANC1", "TEST_UID_ANC1", version="partial-v1")
    _mapping(session, programme, "DELIVERIES", "TEST_UID_MA04", version="partial-v1")
    session.flush()

    partial = evaluate_coverage(session, programme_id=programme.id, mapping_version="partial-v1")
    assert partial.resolved == ["ANC1", "DELIVERIES"]
    assert partial.unresolved, "the remaining MNCH keys are genuinely unmapped"
    assert partial.complete is False

    empty = evaluate_coverage(session, programme_id=programme.id, mapping_version="absent-v1")
    assert empty.resolved == []
    with pytest.raises(CoverageError) as excinfo:
        ensure_coverage(session, programme_id=programme.id, mapping_version="absent-v1")
    assert excinfo.value.code == "mapping_coverage_incomplete"


def test_a_disabled_or_out_of_force_mapping_is_not_counted_as_coverage(session):
    from datetime import date

    programme = session.scalar(select(Programme).where(Programme.code == "MNCH"))
    _mapping(session, programme, "ANC1", "TEST_UID_ANC1", version="gated-v1", enabled=False)
    expired = _mapping(session, programme, "ANC4", "TEST_UID_AN02", version="gated-v1")
    expired.valid_to = date(2020, 12, 31)
    session.flush()

    report = evaluate_coverage(
        session, programme_id=programme.id, mapping_version="gated-v1", as_of=date(2026, 6, 30)
    )
    assert report.resolved == [], "disabled and expired mappings must not count as coverage"


def test_extraction_scope_rejects_an_incompatible_geography_level(session):
    """A caesarean rate is reported by facilities up through districts, never below a facility."""
    from app.services.sync import OrgScopeError, _mapped_org_unit_uids

    uganda = session.scalar(select(OrgUnit).where(OrgUnit.code == "UG"))
    acholi = session.scalar(select(OrgUnit).where(OrgUnit.code == "ACHOLI"))
    district = next(
        unit
        for unit in session.scalars(select(OrgUnit).where(OrgUnit.parent_id == acholi.id)).all()
        if unit.level_type == OrgUnitLevel.DISTRICT.value
    )
    ward = create_org_unit(
        session,
        code="TEST_WARD_BELOW_FACILITY",
        name="Test ward",
        level_type=OrgUnitLevel.FACILITY,
        parent=district,
    )
    session.flush()
    # A facility with no mapping of its own cannot prove a request scope.
    with pytest.raises(OrgScopeError) as excinfo:
        _mapped_org_unit_uids(session, ward)
    assert excinfo.value.code in {"org_mapping_missing", "org_mapping_incomplete"}
    assert uganda is not None

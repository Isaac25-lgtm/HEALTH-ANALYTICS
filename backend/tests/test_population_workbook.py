"""Amendment §2/§3: population workbook checksum, reconciliation, reviewed aliases and draft import."""

import json
import warnings
from pathlib import Path

import pytest
from openpyxl import Workbook
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.db.base import Base
from app.db.session import create_db_engine, reset_engine
from app.domain.enums import OrgUnitLevel
from app.models import AuditLog, OrgUnit, PopulationValue, PopulationVersion, User, UserPermission
from app.services.authorization import AuthorizationError
from app.services.geography import create_org_unit
from app.services.population import approve_population_version, resolve_population
from app.services.population_workbook import (
    HEADER,
    NATIONAL_TOTAL_LABEL,
    VERIFIED_SHA256,
    PopulationWorkbookError,
    apply_population_workbook,
    decide_alias,
    file_sha256,
    propose_alias,
    read_population_workbook,
    reconcile_workbook,
)
from app.services.seed import seed_reference_data
from tests.conftest import SEED_PASSWORD

OWNER_WORKBOOK = Path(__file__).resolve().parents[2] / "Uganda_District_City_Populations_2024_2030.xlsx"
owner_workbook = pytest.mark.skipif(not OWNER_WORKBOOK.is_file(), reason="Owner-supplied workbook is not present.")

# Handoff Appendix N.5 regression fixture (2024 census, 2025 projection).
N5 = {
    "Agago": (307_235, 314_700),
    "Amuru": (247_574, 261_130),
    "Gulu City": (233_271, 247_560),
    "Gulu": (135_373, 142_280),
    "Kitgum": (239_655, 242_410),
    "Lamwo": (213_156, 227_180),
    "Nwoya": (220_593, 242_910),
    "Omoro": (207_339, 225_620),
    "Pader": (240_159, 248_910),
}

# Synthetic test values only. They are not official populations.
SYNTHETIC = [
    ("Pader", "District", "Northern", [1_000, 1_010, 1_020, 1_030, 1_040, 1_050, 1_060]),
    ("Kitgum", "District", "Northern", [2_000, 2_010, 2_020, 2_030, 2_040, 2_050, 2_060]),
    ("Gulu City", "City", "Northern", [3_000, 3_010, 3_020, 3_030, 3_040, 3_050, 3_060]),
    ("Gulu", "District", "Northern", [4_000, 4_010, 4_020, 4_030, 4_040, 4_050, 4_060]),
    ("Manafwa", "District", "Eastern", [5_000, 5_010, 5_020, 5_030, 5_040, 5_050, 5_060]),
    ("Kampala Capital City", "City", "Central", [6_000, 6_010, 6_020, 6_030, 6_040, 6_050, 6_060]),
]


def _quiet_read(path, **kwargs):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return read_population_workbook(path, **kwargs)


def _write_workbook(path: Path, units=SYNTHETIC, *, national=None, header=HEADER) -> str:
    book = Workbook()
    sheet = book.active
    sheet.title = "District_City_Populations"
    sheet.append(["Synthetic population workbook for automated tests. Not official data."])
    sheet.append(["Structure mirrors the owner-supplied workbook."])
    sheet.append([None])
    sheet.append(list(header))
    totals = [0] * 7
    for name, unit_type, region, values in units:
        sheet.append([name, unit_type, region, *values])
        totals = [left + right for left, right in zip(totals, values, strict=True)]
    sheet.append([NATIONAL_TOTAL_LABEL, None, None, *(national or totals)])
    book.save(path)
    return file_sha256(path)


def _unit(session, code):
    return session.scalar(select(OrgUnit).where(OrgUnit.code == code))


def _user(session, username):
    return session.scalar(select(User).where(User.username == username))


def _grant(session, username, *actions):
    user = _user(session, username)
    for action in actions:
        session.add(UserPermission(user_id=user.id, action=action))
    session.flush()
    return user


def _geography(session):
    acholi, teso, uganda = _unit(session, "ACHOLI"), _unit(session, "TESO"), _unit(session, "UG")
    central = create_org_unit(
        session, code="TEST_CENTRAL", name="Central (synthetic)", level_type=OrgUnitLevel.REGION, parent=uganda
    )
    return {
        "gulu_city": create_org_unit(
            session, code="TEST_GULU_CITY", name="Gulu City", level_type=OrgUnitLevel.CITY, parent=acholi
        ),
        "gulu_district": create_org_unit(
            session, code="TEST_GULU_DISTRICT", name="Gulu District", level_type=OrgUnitLevel.DISTRICT, parent=acholi
        ),
        "manafa": create_org_unit(
            session, code="TEST_MANAFA", name="Manafa", level_type=OrgUnitLevel.DISTRICT, parent=teso
        ),
        "kampala": create_org_unit(
            session, code="TEST_KAMPALA", name="Kampala", level_type=OrgUnitLevel.CITY, parent=central
        ),
        "central": central,
    }


def _statuses(report):
    return {item.unit.name: item.status for item in report.units}


def _approve_aliases(session, units, *, proposer, approver):
    decisions = (
        ("Gulu", "District", units["gulu_district"], "Owner decision: Gulu District is the workbook's Gulu."),
        ("Manafwa", "District", units["manafa"], "Owner decision: Manafa/Manafwa spelling variant."),
        ("Kampala Capital City", "City", units["kampala"], "Owner decision: Kampala/Kampala Capital City."),
    )
    for name, unit_type, target, note in decisions:
        alias = propose_alias(
            session, proposer, source_unit_name=name, source_unit_type=unit_type, org_unit_id=target.id, note=note
        )
        decide_alias(session, approver, alias.id, approve=True, note="Reviewed against the owner instruction.")


@owner_workbook
def test_owner_workbook_identity_counts_and_n5_values():
    before = file_sha256(OWNER_WORKBOOK)
    assert before == VERIFIED_SHA256
    extract = _quiet_read(OWNER_WORKBOOK)
    summary = extract.summary()
    assert (summary["unit_rows"], summary["districts"], summary["cities"]) == (146, 135, 11)
    assert extract.years == [2024, 2025, 2026, 2027, 2028, 2029, 2030]
    assert extract.cell_count == 1_022
    assert NATIONAL_TOTAL_LABEL not in {unit.name for unit in extract.units}
    for year in extract.years:
        assert sum(unit.values[year] for unit in extract.units) == extract.national_total[year]
    by_name = {unit.name: unit for unit in extract.units}
    assert {name: (by_name[name].values[2024], by_name[name].values[2025]) for name in N5} == N5
    assert sum(by_name[name].values[2024] for name in N5) == 2_044_355
    assert sum(by_name[name].values[2025] for name in N5) == 2_152_700
    assert (by_name["Gulu"].unit_type, by_name["Gulu City"].unit_type) == ("District", "City")
    assert by_name["Kampala Capital City"].unit_type == "City"
    assert "Manafwa" in by_name and "Manafa" not in by_name
    assert file_sha256(OWNER_WORKBOOK) == before


@owner_workbook
def test_owner_workbook_dry_run_against_the_synthetic_seed_is_blocked(session):
    report = reconcile_workbook(session, _quiet_read(OWNER_WORKBOOK))
    statuses = _statuses(report)
    assert {name for name, status in statuses.items() if status == "matched_exact"} == {"Pader", "Kitgum", "Soroti"}
    assert report.can_apply is False
    assert session.scalar(select(func.count()).select_from(PopulationVersion)) == 0


def test_checksum_is_verified_before_reading(tmp_path):
    path = tmp_path / "synthetic.xlsx"
    sha = _write_workbook(path)
    with pytest.raises(PopulationWorkbookError) as default_checksum:
        _quiet_read(path)
    assert default_checksum.value.code == "checksum_mismatch"
    assert len(_quiet_read(path, expected_sha256=sha).units) == len(SYNTHETIC)
    with path.open("ab") as handle:
        handle.write(b"\0")
    with pytest.raises(PopulationWorkbookError) as changed:
        _quiet_read(path, expected_sha256=sha)
    assert changed.value.code == "checksum_mismatch"
    with pytest.raises(PopulationWorkbookError) as missing:
        _quiet_read(tmp_path / "absent.xlsx", expected_sha256=sha)
    assert missing.value.code == "workbook_missing"


def test_national_total_is_excluded_and_must_equal_the_unit_sum(tmp_path):
    path = tmp_path / "synthetic.xlsx"
    extract = _quiet_read(path, expected_sha256=_write_workbook(path))
    assert NATIONAL_TOTAL_LABEL not in {unit.name for unit in extract.units}
    assert extract.national_total[2024] == sum(values[0] for *_, values in SYNTHETIC)
    wrong = tmp_path / "wrong_total.xlsx"
    sha = _write_workbook(wrong, national=[1, 1, 1, 1, 1, 1, 1])
    with pytest.raises(PopulationWorkbookError) as mismatch:
        _quiet_read(wrong, expected_sha256=sha)
    assert mismatch.value.code == "national_total_mismatch"


def test_structure_and_duplicate_rows_are_rejected(tmp_path):
    duplicate = tmp_path / "duplicate.xlsx"
    rows = [*SYNTHETIC, ("PADER ", "District", "Northern", [1, 1, 1, 1, 1, 1, 1])]
    sha = _write_workbook(duplicate, rows)
    with pytest.raises(PopulationWorkbookError) as duplicated:
        _quiet_read(duplicate, expected_sha256=sha)
    assert duplicated.value.code == "duplicate_source_units"
    header = tmp_path / "header.xlsx"
    sha = _write_workbook(header, header=("Unit", *HEADER[1:]))
    with pytest.raises(PopulationWorkbookError) as bad_header:
        _quiet_read(header, expected_sha256=sha)
    assert bad_header.value.code == "header_mismatch"
    typed = tmp_path / "typed.xlsx"
    sha = _write_workbook(typed, [("Pader", "Sub-county", "Northern", [1, 1, 1, 1, 1, 1, 1])])
    with pytest.raises(PopulationWorkbookError) as bad_type:
        _quiet_read(typed, expected_sha256=sha)
    assert bad_type.value.code == "invalid_unit_type"


def test_reconciliation_is_exact_and_blocks_unreviewed_names(session, tmp_path):
    units = _geography(session)
    path = tmp_path / "synthetic.xlsx"
    extract = _quiet_read(path, expected_sha256=_write_workbook(path))
    report = reconcile_workbook(session, extract)
    # A unit whose name ends with its own type ("Gulu District", a district) is the same unit the
    # source calls by its bare name plus a Type column ("Gulu", District). DHIS2 spells names that
    # way for every Ugandan district, so treating the redundant suffix as a different name would
    # demand an alias decision for all 143 straightforward units. The suffix is a restatement of
    # the unit's own level type and nothing else is stripped, so this stays an exact match rather
    # than a fuzzy one. Genuinely different spellings are still blocked below.
    assert _statuses(report) == {
        "Pader": "matched_exact",
        "Kitgum": "matched_exact",
        "Gulu City": "matched_exact",
        "Gulu": "matched_exact",
        "Manafwa": "unmatched",
        "Kampala Capital City": "unmatched",
    }
    # "Gulu" resolves to the district and never to the city: the type filter keeps them distinct
    # even though both index under "gulu".
    gulu = next(item for item in report.units if item.unit.name == "Gulu")
    assert gulu.org_unit.id == units["gulu_district"].id
    assert report.can_apply is False
    uncovered = {unit.code for unit in report.internal_units_without_source}
    assert {"TEST_MANAFA", "TEST_KAMPALA", "SOROTI"} <= uncovered
    matched = next(item for item in report.units if item.unit.name == "Gulu City")
    assert matched.org_unit.id == units["gulu_city"].id
    admin = _user(session, "admin.user")
    with pytest.raises(PopulationWorkbookError) as blocked:
        apply_population_workbook(session, admin, path, version_code="TEST_WB", expected_sha256=extract.sha256)
    assert blocked.value.code == "reconciliation_blocked"
    assert session.scalar(select(func.count()).select_from(PopulationVersion)) == 0


def test_type_mismatch_ambiguity_and_duplicate_targets_block(session, tmp_path):
    teso = _unit(session, "TESO")
    create_org_unit(session, code="TEST_LAMWO", name="Lamwo", level_type=OrgUnitLevel.DISTRICT, parent=teso)
    create_org_unit(session, code="TEST_OMORO_A", name="Omoro", level_type=OrgUnitLevel.DISTRICT, parent=teso)
    create_org_unit(session, code="TEST_OMORO_B", name="Omoro", level_type=OrgUnitLevel.DISTRICT, parent=teso)
    path = tmp_path / "edge.xlsx"
    rows = [
        ("Lamwo", "City", "Northern", [1, 1, 1, 1, 1, 1, 1]),
        ("Omoro", "District", "Northern", [2, 2, 2, 2, 2, 2, 2]),
        ("Soroti", "District", "Eastern", [3, 3, 3, 3, 3, 3, 3]),
        ("Soroti Municipality", "District", "Eastern", [4, 4, 4, 4, 4, 4, 4]),
    ]
    extract = _quiet_read(path, expected_sha256=_write_workbook(path, rows))
    admin = _user(session, "admin.user")
    alias = propose_alias(
        session,
        admin,
        source_unit_name="Soroti Municipality",
        source_unit_type="District",
        org_unit_id=_unit(session, "SOROTI").id,
        note="Deliberately wrong proposal used to test duplicate targets.",
    )
    decide_alias(session, admin, alias.id, approve=True, note="Synthetic test decision.")
    statuses = _statuses(reconcile_workbook(session, extract))
    assert statuses == {
        "Lamwo": "type_mismatch",
        "Omoro": "ambiguous",
        "Soroti": "duplicate_target",
        "Soroti Municipality": "duplicate_target",
    }


def test_alias_decisions_are_reviewed_audited_and_preserve_both_names(session, tmp_path):
    units = _geography(session)
    proposer = _grant(session, "acholi.analyst", "edit_population", "approve_population")
    reviewer = _grant(session, "national.analyst", "approve_population")
    path = tmp_path / "synthetic.xlsx"
    extract = _quiet_read(path, expected_sha256=_write_workbook(path))
    alias = propose_alias(
        session,
        proposer,
        source_unit_name="Gulu",
        source_unit_type="District",
        org_unit_id=units["gulu_district"].id,
        note="Gulu in the workbook is the district, distinct from Gulu City.",
    )
    assert _statuses(reconcile_workbook(session, extract))["Gulu"] == "pending_alias"
    with pytest.raises(AuthorizationError) as self_decision:
        decide_alias(session, proposer, alias.id, approve=True, note="Self review")
    assert self_decision.value.code == "forbidden_action"
    with pytest.raises(AuthorizationError):
        decide_alias(session, reviewer, alias.id, approve=True, note="  ")
    decide_alias(session, reviewer, alias.id, approve=True, note="Confirmed against the district list.")
    report = reconcile_workbook(session, extract)
    gulu = next(item for item in report.units if item.unit.name == "Gulu")
    assert gulu.status == "matched_alias"
    assert gulu.org_unit.id == units["gulu_district"].id
    assert (alias.source_unit_name, alias.target_name) == ("Gulu", "Gulu District")
    assert alias.decided_by_user_id == reviewer.id and alias.decided_at is not None
    with pytest.raises(AuthorizationError) as outside:
        propose_alias(
            session,
            proposer,
            source_unit_name="Kampala Capital City",
            source_unit_type="City",
            org_unit_id=units["kampala"].id,
            note="Outside the proposer's geography.",
        )
    assert outside.value.code == "forbidden_geography"
    admin = _user(session, "admin.user")
    with pytest.raises(AuthorizationError):
        propose_alias(
            session,
            admin,
            source_unit_name="Kampala Capital City",
            source_unit_type="City",
            org_unit_id=units["central"].id,
            note="A region is not a district-equivalent peer.",
        )
    rejected = propose_alias(
        session,
        admin,
        source_unit_name="Manafwa",
        source_unit_type="District",
        org_unit_id=units["manafa"].id,
        note="Spelling variant pending owner confirmation.",
    )
    decide_alias(session, reviewer, rejected.id, approve=False, note="Owner has not confirmed yet.")
    assert _statuses(reconcile_workbook(session, extract))["Manafwa"] == "rejected_alias"
    actions = set(session.scalars(select(AuditLog.action)).all())
    assert {"population_alias_proposed", "population_alias_approved", "population_alias_rejected"} <= actions


def test_apply_creates_drafts_with_source_identity_and_only_district_city_values(session, tmp_path):
    units = _geography(session)
    admin = _user(session, "admin.user")
    reviewer = _grant(session, "national.analyst", "approve_population")
    _approve_aliases(session, units, proposer=admin, approver=reviewer)
    path = tmp_path / "synthetic.xlsx"
    sha = _write_workbook(path)
    versions = apply_population_workbook(session, admin, path, version_code="TEST_WB", expected_sha256=sha)
    assert [version.code for version in versions] == ["TEST_WB_CENSUS2024", "TEST_WB_PROJ2025_2030"]
    assert [version.population_type for version in versions] == ["census", "projection"]
    for version in versions:
        assert version.approval_status == "draft"
        assert (version.source_sha256, version.source_file_name) == (sha, "synthetic.xlsx")
        assert version.source_sheet == "District_City_Populations"
        assert version.created_at is not None and version.imported_by_user_id == admin.id
    values = session.scalars(select(PopulationValue)).all()
    assert len(values) == len(SYNTHETIC) * 7
    gulu = [row for row in values if row.org_unit_id == units["gulu_district"].id and row.year == 2024]
    assert len(gulu) == 1
    source = (gulu[0].source_unit_name, gulu[0].source_unit_type, gulu[0].source_region)
    assert source == ("Gulu", "District", "Northern")
    assert gulu[0].source_column_label == "2024 Census"
    forbidden = {_unit(session, code).id for code in ("UG", "ACHOLI", "PADER_TOWN", "PADER_HC_III")}
    assert not [row for row in values if row.org_unit_id in forbidden]
    acholi = _unit(session, "ACHOLI")
    assert resolve_population(session, acholi, period_key="FY2024/25").status == "unavailable"
    for version in versions:
        approve_population_version(session, reviewer, version.id, reason="Synthetic approval")
    census = resolve_population(session, acholi, period_key="FY2024/25")
    assert census.status == "ok"
    assert census.population == 1_000 + 2_000 + 3_000 + 4_000
    assert census.aggregation_level == "district_equivalent"
    assert census.policy == "children"
    projection = resolve_population(session, acholi, period_key="FY2025/26")
    assert projection.population == 1_010 + 2_010 + 3_010 + 4_010
    assert resolve_population(session, _unit(session, "PADER_HC_III"), period_key="FY2024/25").status == "unavailable"
    with pytest.raises(PopulationWorkbookError) as again:
        apply_population_workbook(session, admin, path, version_code="TEST_WB_AGAIN", expected_sha256=sha)
    assert again.value.code == "already_imported"


def test_national_total_is_imported_only_when_explicitly_requested(session, tmp_path):
    units = _geography(session)
    admin = _user(session, "admin.user")
    reviewer = _grant(session, "national.analyst", "approve_population")
    _approve_aliases(session, units, proposer=admin, approver=reviewer)
    path = tmp_path / "synthetic.xlsx"
    sha = _write_workbook(path)
    with pytest.raises(PopulationWorkbookError) as unnamed:
        apply_population_workbook(
            session, admin, path, version_code="TEST_NT", expected_sha256=sha, include_national_total=True
        )
    assert unnamed.value.code == "national_unit_required"
    versions = apply_population_workbook(
        session,
        admin,
        path,
        version_code="TEST_NT",
        expected_sha256=sha,
        include_national_total=True,
        national_org_unit_code="UG",
    )
    uganda = _unit(session, "UG")
    national = session.scalars(select(PopulationValue).where(PopulationValue.org_unit_id == uganda.id)).all()
    assert {row.source_unit_type for row in national} == {"national_total"}
    for version in versions:
        approve_population_version(session, reviewer, version.id, reason="Synthetic approval")
    resolved = resolve_population(session, uganda, period_key="FY2024/25")
    assert resolved.policy == "direct"
    assert resolved.population == sum(values[0] for *_, values in SYNTHETIC)


def test_importer_needs_permission_and_full_geography(session, tmp_path):
    units = _geography(session)
    admin = _user(session, "admin.user")
    reviewer = _grant(session, "national.analyst", "approve_population")
    _approve_aliases(session, units, proposer=admin, approver=reviewer)
    path = tmp_path / "synthetic.xlsx"
    sha = _write_workbook(path)
    with pytest.raises(AuthorizationError):
        apply_population_workbook(session, _user(session, "view.only"), path, version_code="X", expected_sha256=sha)
    regional = _grant(session, "acholi.analyst", "edit_population")
    with pytest.raises(AuthorizationError) as outside:
        apply_population_workbook(session, regional, path, version_code="X", expected_sha256=sha)
    assert outside.value.code == "forbidden_geography"


def test_cli_dry_run_reports_and_writes_nothing(tmp_path, monkeypatch, capsys):
    from scripts.import_population_workbook import main

    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'cli.db'}")
    get_settings.cache_clear()
    reset_engine()
    engine = create_db_engine()
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, future=True)
    with factory() as seed:
        seed_reference_data(seed, SEED_PASSWORD)
        seed.commit()
    path = tmp_path / "synthetic.xlsx"
    sha = _write_workbook(path)
    try:
        assert main(["--workbook", str(path), "--expected-sha256", sha]) == 0
        report = json.loads(capsys.readouterr().out)
        assert report["mode"] == "dry_run"
        assert report["can_apply"] is False
        assert report["workbook"]["checksum_verified"] is True
        assert main(["--workbook", str(path), "--expected-sha256", sha, "--apply", "--version-code", "CLI",
                     "--username", "admin.user"]) == 2
        assert json.loads(capsys.readouterr().out)["error"] == "reconciliation_blocked"
        assert main(["--workbook", str(path)]) == 2
        assert json.loads(capsys.readouterr().out)["error"] == "checksum_mismatch"
        with factory() as check:
            assert check.scalar(select(func.count()).select_from(PopulationVersion)) == 0
    finally:
        engine.dispose()
        get_settings.cache_clear()
        reset_engine()

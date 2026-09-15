"""Fresh production database: migrations -> reference bootstrap -> first administrator -> login.

The bootstrap creates only approved non-secret reference configuration and fails closed when
existing configuration differs. The same release flow runs on PostgreSQL in
``test_postgres_reference_bootstrap.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.db.session import reset_engine
from app.domain.indicator_catalog import INDICATOR_CATALOG, QUALITY_RULE_CATALOG
from app.main import app
from app.models import (
    AnalysisSnapshot,
    CalculatedValue,
    EventFieldMapping,
    FacilityPopulationEntry,
    Geometry,
    Indicator,
    IndicatorSourceMapping,
    IndicatorVersion,
    OrgUnit,
    OrgUnitMapping,
    PeriodPopulationRule,
    PopulationImportBatch,
    PopulationValue,
    PopulationVersion,
    Programme,
    QualityRule,
    RawAggregateValue,
    RawEventSnapshot,
    Role,
    RolePermission,
    SourceMapping,
    User,
)
from app.services.reference_bootstrap import (
    ROLE_CATALOG,
    ReferenceBootstrapConflict,
    bootstrap_reference_data,
    period_rule_specs,
)
from scripts import bootstrap_reference_data as bootstrap_cli
from scripts import create_initial_admin as admin_cli

ADMIN_PASSWORD = "uat-operator-chosen-passphrase-7"

# Tables that must stay empty after a production bootstrap: no people, no synthetic or real
# sub-national geography, no DHIS2 identifiers, no observations, no populations, no boundaries.
MUST_STAY_EMPTY = (
    User,
    OrgUnitMapping,
    IndicatorSourceMapping,
    SourceMapping,
    EventFieldMapping,
    RawAggregateValue,
    RawEventSnapshot,
    PopulationVersion,
    PopulationValue,
    FacilityPopulationEntry,
    PopulationImportBatch,
    Geometry,
    CalculatedValue,
    AnalysisSnapshot,
)


def _alembic_cfg() -> Config:
    return Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))


def _count(session, model) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


def reference_counts(session) -> dict[str, int]:
    return {
        "programmes": _count(session, Programme),
        "roles": _count(session, Role),
        "role_permissions": _count(session, RolePermission),
        "org_units": _count(session, OrgUnit),
        "indicators": _count(session, Indicator),
        "indicator_versions": _count(session, IndicatorVersion),
        "quality_rules": _count(session, QualityRule),
        "period_rules": _count(session, PeriodPopulationRule),
    }


def expected_reference_counts() -> dict[str, int]:
    return {
        "programmes": 3,
        "roles": len(ROLE_CATALOG),
        "role_permissions": sum(len(actions) for actions in ROLE_CATALOG.values()),
        "org_units": 1,
        "indicators": len(INDICATOR_CATALOG),
        "indicator_versions": len(INDICATOR_CATALOG),
        "quality_rules": len(QUALITY_RULE_CATALOG),
        "period_rules": len(period_rule_specs()),
    }


def point_at(monkeypatch, url: str) -> None:
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("SEED_DEV_DATA", "false")
    get_settings.cache_clear()
    reset_engine()


def run_release(monkeypatch, url: str, capsys) -> None:
    """The documented release order, executed exactly as an operator would."""
    point_at(monkeypatch, url)
    command.upgrade(_alembic_cfg(), "head")

    assert bootstrap_cli.main([]) == 0
    first = capsys.readouterr().out
    assert "Created:" in first and "programmes=3" in first

    # A second release run creates nothing.
    assert bootstrap_cli.main([]) == 0
    assert "Created: nothing." in capsys.readouterr().out

    engine = create_engine(url, future=True)
    try:
        with sessionmaker(bind=engine, future=True)() as session:
            assert reference_counts(session) == expected_reference_counts()
            for model in MUST_STAY_EMPTY:
                assert _count(session, model) == 0, model.__tablename__
            root = session.scalar(select(OrgUnit))
            assert (root.code, root.level_type, root.parent_id) == ("UG", "country", None)
            # Undated: production keeps every catalogue version unavailable until dated or the
            # governed fallback is explicitly enabled.
            assert session.scalar(select(func.count()).where(IndicatorVersion.valid_from.is_not(None))) == 0
            assert set(session.scalars(select(Programme.code)).all()) == {"MNCH", "EPI", "MPDSR"}
            assert session.scalar(select(Programme.sensitive).where(Programme.code == "MPDSR")) is True
    finally:
        engine.dispose()

    monkeypatch.setenv("HPIP_ADMIN_PASSWORD", ADMIN_PASSWORD)
    assert admin_cli.main(["--username", "uat.admin", "--display-name", "UAT Administrator", "--no-prompt"]) == 0
    output = capsys.readouterr().out
    assert "scoped to UG" in output and ADMIN_PASSWORD not in output

    app.dependency_overrides.clear()
    with TestClient(app) as client:
        response = client.post("/auth/login", json={"username": "uat.admin", "password": ADMIN_PASSWORD})
        assert response.status_code == 200, response.text
        assert "hpip_session" in response.cookies
        context = client.get("/me/context")
        assert context.status_code == 200, context.text
        body = context.json()
        assert body["landing_org_unit"]["code"] == "UG"
        assert "MPDSR" not in body["programmes"] and {"MNCH", "EPI"} <= set(body["programmes"])
        refused = client.post("/auth/login", json={"username": "uat.admin", "password": "wrong-password-value"})
        assert refused.status_code in (400, 401)


@pytest.fixture()
def fresh_sqlite(tmp_path, monkeypatch):
    url = f"sqlite+pysqlite:///{(tmp_path / 'fresh.db').as_posix()}"
    yield url
    get_settings.cache_clear()
    reset_engine()


def test_fresh_database_release_bootstrap_admin_and_login(fresh_sqlite, monkeypatch, capsys):
    run_release(monkeypatch, fresh_sqlite, capsys)


def test_bootstrap_refuses_a_database_that_is_not_migrated(fresh_sqlite, monkeypatch, capsys):
    point_at(monkeypatch, fresh_sqlite)
    assert bootstrap_cli.main([]) == 2
    assert "Run the migrations first" in capsys.readouterr().out


def test_admin_creation_before_bootstrap_explains_the_missing_step(fresh_sqlite, monkeypatch, capsys):
    point_at(monkeypatch, fresh_sqlite)
    command.upgrade(_alembic_cfg(), "head")
    monkeypatch.setenv("HPIP_ADMIN_PASSWORD", ADMIN_PASSWORD)
    assert admin_cli.main(["--username", "early.admin", "--no-prompt"]) == 2
    assert "bootstrap_reference_data.py" in capsys.readouterr().out


def test_check_mode_writes_nothing(fresh_sqlite, monkeypatch, capsys):
    point_at(monkeypatch, fresh_sqlite)
    command.upgrade(_alembic_cfg(), "head")
    assert bootstrap_cli.main(["--check"]) == 0
    assert "Would create:" in capsys.readouterr().out
    engine = create_engine(fresh_sqlite, future=True)
    with sessionmaker(bind=engine, future=True)() as session:
        assert all(count == 0 for count in reference_counts(session).values())
    engine.dispose()


def test_conflicting_configuration_fails_closed_through_the_cli(fresh_sqlite, monkeypatch, capsys):
    point_at(monkeypatch, fresh_sqlite)
    command.upgrade(_alembic_cfg(), "head")
    assert bootstrap_cli.main([]) == 0
    engine = create_engine(fresh_sqlite, future=True)
    factory = sessionmaker(bind=engine, future=True)
    with factory() as session:
        session.scalar(select(Programme).where(Programme.code == "MPDSR")).sensitive = False
        session.delete(session.scalars(select(QualityRule)).first())
        session.commit()
        rules_before = _count(session, QualityRule)
    capsys.readouterr()
    assert bootstrap_cli.main([]) == 3
    output = capsys.readouterr().out
    assert "programme MPDSR: sensitive differs" in output and "nothing was written" in output
    with factory() as session:
        # The missing rule was not recreated and the edited row was not overwritten.
        assert _count(session, QualityRule) == rules_before
        assert session.scalar(select(Programme.sensitive).where(Programme.code == "MPDSR")) is False
    engine.dispose()


# ---------------------------------------------------------------------------
# Service-level behaviour on the seeded test session
# ---------------------------------------------------------------------------


def test_the_development_seed_is_compatible_with_the_production_reference(session):
    before = reference_counts(session)
    report = bootstrap_reference_data(session)
    assert not report.changed
    assert reference_counts(session) == before


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (
            lambda s: setattr(s.scalar(select(Programme).where(Programme.code == "EPI")), "name", "Renamed"),
            "programme EPI: name differs",
        ),
        (
            lambda s: s.add(
                RolePermission(
                    role_id=s.scalar(select(Role.id).where(Role.code == "view_only")), action="manage_users"
                )
            ),
            "role view_only: permissions differ",
        ),
        (
            lambda s: setattr(
                s.scalar(
                    select(IndicatorVersion)
                    .join(Indicator, Indicator.id == IndicatorVersion.indicator_id)
                    .where(Indicator.code == "ANC1_COVERAGE")
                ),
                "target",
                "99",
            ),
            "indicator ANC1_COVERAGE: target differs",
        ),
        (
            lambda s: setattr(
                s.scalar(
                    select(PeriodPopulationRule).where(
                        PeriodPopulationRule.financial_year_key == "FY2025/26",
                        PeriodPopulationRule.programme_id.is_(None),
                    )
                ),
                "population_year",
                2026,
            ),
            "period rule FY2025/26 (all programmes): population_year differs",
        ),
        (
            lambda s: setattr(s.scalar(select(OrgUnit).where(OrgUnit.code == "UG")), "level_type", "region"),
            "org unit UG: level_type differs",
        ),
    ],
)
def test_each_kind_of_conflict_is_detected_and_nothing_is_written(session, mutate, expected):
    mutate(session)
    session.commit()
    removed = session.scalars(
        select(PeriodPopulationRule).where(PeriodPopulationRule.financial_year_key == "2030")
    ).all()
    for row in removed:
        session.delete(row)
    session.commit()
    with pytest.raises(ReferenceBootstrapConflict) as raised:
        bootstrap_reference_data(session)
    session.rollback()
    assert any(expected in item for item in raised.value.conflicts), raised.value.conflicts
    assert raised.value.code == "reference_configuration_conflict"
    assert session.scalar(select(func.count()).where(PeriodPopulationRule.financial_year_key == "2030")) == 0


def test_conflict_messages_contain_no_values_only_field_names(session):
    session.scalar(select(Programme).where(Programme.code == "EPI")).name = "Operator 0772 123456"
    session.commit()
    with pytest.raises(ReferenceBootstrapConflict) as raised:
        bootstrap_reference_data(session)
    session.rollback()
    assert "0772" not in " ".join(raised.value.conflicts)


def test_missing_rows_are_added_without_touching_existing_ones(session):
    target = session.scalar(
        select(PeriodPopulationRule).where(
            PeriodPopulationRule.financial_year_key == "2027", PeriodPopulationRule.programme_id.is_(None)
        )
    )
    session.delete(target)
    session.commit()
    report = bootstrap_reference_data(session)
    session.commit()
    assert report.created == {"period_rules": 1}
    assert reference_counts(session)["period_rules"] == len(period_rule_specs())

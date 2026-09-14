import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select, text

from app.config import Settings, get_settings, validate_runtime_settings
from app.models import OrgUnit, User
from app.services.modules import evaluate_module
from scripts.backup_restore import backup_sqlite, refuse_non_sqlite, restore_sqlite
from tests.conftest import auth_header, login, query_dashboard
from tests.helpers import put_population, put_raw


def _unit(session, code):
    return session.scalar(select(OrgUnit).where(OrgUnit.code == code))


def _load_gold_sources(session, org, period, source):
    put_population(
        session,
        org,
        source["population_year"],
        source["population"],
        code=f"GOLD_POP_{source['population_year']}",
    )
    for key in (
        "ANC1",
        "ANC1_FT",
        "ANC4",
        "ANC8",
        "IPT3",
        "HB_TESTED",
        "IFA_30",
        "ULTRASOUND",
        "ANC1_AGE_LT15",
        "ANC1_AGE_15_19",
    ):
        put_raw(session, org, period, key, source[key])


def test_gold_standard_fixture_reproduces_appendix_t_labels(session):
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "acholi_gold_standard.json").read_text(encoding="utf-8")
    )
    assert fixture["verified_fixture"] is True
    assert "not production" in fixture["label"].lower()
    acholi = _unit(session, fixture["org_unit_code"])
    admin = session.scalar(select(User).where(User.username == "admin.user"))
    for period, source in fixture["sources"].items():
        _load_gold_sources(session, acholi, period, source)
    result = evaluate_module(
        session,
        user=admin,
        org_unit_id=acholi.id,
        period=fixture["period"],
        module=fixture["module"],
        comparison_period=fixture["comparison_period"],
        include_children=False,
    )
    by_code = {row["indicator_code"]: row for row in result["indicators"]}
    expected = fixture["expected"]
    assert round(by_code["ANC1_COVERAGE"]["raw_value"], 1) == expected["ANC1_COVERAGE"]["raw_value"]
    assert by_code["ANC1_COVERAGE"]["status"] == expected["ANC1_COVERAGE"]["status"]
    change_pp = by_code["ANC1_COVERAGE"]["change"]["percentage_point_change"]
    assert round(change_pp, 1) == expected["ANC1_COVERAGE"]["change_pp"]
    assert by_code["IFA_COVERAGE"]["raw_value"] > 100
    assert by_code["TEENAGE_PREGNANCY"]["status"] == expected["TEENAGE_PREGNANCY"]["status"]


def test_ops_status_requires_admin_and_hides_secrets(client):
    blocked = login(client, "national.analyst")
    denied = client.get("/ops/status", headers=auth_header(blocked))
    assert denied.status_code == 403
    csrf = login(client, "admin.user")
    response = client.get("/ops/status", headers=auth_header(csrf))
    assert response.status_code == 200
    body = response.json()
    encoded = json.dumps(body).lower()
    assert "password" not in encoded
    assert "api_key" not in encoded
    assert "auth_secret" not in encoded
    assert body["secrets_exposed"] is False
    assert body["ai_enabled"] is False


def test_export_rate_limit(client, session, tmp_path, monkeypatch):
    pader = _unit(session, "PADER")
    put_population(session, pader, 2024, 1_000_000, code="RL_POP")
    put_raw(session, pader, "FY2024/25", "ANC1", 10_000)
    session.commit()
    monkeypatch.setattr(get_settings(), "export_dir", str(tmp_path))
    monkeypatch.setattr(get_settings(), "export_rate_limit", 1)
    csrf = login(client, "pader.focal")
    headers = auth_header(csrf)
    dash = query_dashboard(client, headers, pader.id).json()
    body = {
        "org_unit_id": str(pader.id),
        "period": "FY2024/25",
        "module": "anc",
        "analysis_snapshot_id": dash["analysis_snapshot_id"],
        "view_hash": dash["view_hash"],
    }
    first = client.post("/exports/excel", json=body, headers=headers)
    assert first.status_code == 202, first.text
    second = client.post("/exports/excel", json=body, headers=headers)
    assert second.status_code == 429
    assert second.json()["detail"]["code"] == "rate_limited"


def test_sqlite_backup_restore_round_trip(tmp_path):
    source = tmp_path / "live.sqlite"
    backup = tmp_path / "backup.sqlite"
    restored = tmp_path / "restored.sqlite"
    engine = create_engine(f"sqlite+pysqlite:///{source}", future=True)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE marker (value TEXT)"))
        conn.execute(text("INSERT INTO marker (value) VALUES ('original')"))
    engine.dispose()
    backup_sqlite(source, backup)
    engine = create_engine(f"sqlite+pysqlite:///{source}", future=True)
    with engine.begin() as conn:
        conn.execute(text("UPDATE marker SET value = 'mutated'"))
    engine.dispose()
    restore_sqlite(backup, restored)
    check = create_engine(f"sqlite+pysqlite:///{restored}", future=True)
    with check.connect() as conn:
        value = conn.execute(text("SELECT value FROM marker")).scalar_one()
    check.dispose()
    assert value == "original"


def test_backup_helper_refuses_postgres_url():
    with pytest.raises(ValueError, match="SQLite-only"):
        refuse_non_sqlite("postgresql+psycopg://hpip:change-me@127.0.0.1:5432/hpip_dev")


def test_production_ai_without_key_is_rejected():
    settings = Settings(
        app_env="production",
        database_url="postgresql+psycopg://hpip:change-me@127.0.0.1:5432/hpip_prod",
        auth_secret="a-long-production-secret-value-32ch",
        seed_dev_data=False,
        seed_password="not-the-dev-default-password",
        auth_cookie_secure=True,
        sync_execution="queue",
        ai_enabled=True,
        ai_api_key="",
    )
    errors = validate_runtime_settings(settings)
    assert any("AI_API_KEY" in error for error in errors)

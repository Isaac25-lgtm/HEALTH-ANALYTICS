from __future__ import annotations

import base64
from pathlib import Path

from dotenv import dotenv_values

from scripts.configure_live_local import _environment


def test_live_local_environment_round_trips_rotated_secret_characters(tmp_path):
    password = "spaces # dollars ${NOT_EXPANDED} apostrophe' backslash\\ end"
    document = _environment(
        host="127.0.0.1",
        port=5432,
        app_user="hpip_app",
        app_password="database-secret",
        database="hpip_live",
        dhis2_username="real.user",
        dhis2_password=password,
    )
    path = tmp_path / ".env"
    path.write_text(document, encoding="utf-8")

    parsed = dotenv_values(path)
    assert "DHIS2_PASSWORD" not in parsed
    assert base64.b64decode(parsed["DHIS2_PASSWORD_B64"]).decode("utf-8") == password
    assert parsed["DHIS2_USERNAME"] == "real.user"
    assert parsed["SEED_DEV_DATA"] == "false"


def test_disposable_e2e_api_cannot_inherit_a_live_dhis2_environment():
    """The synthetic end-to-end harness must be offline regardless of the developer's .env.

    `Settings` reads the repository-root `.env`, so a workstation configured for live DHIS2 would
    otherwise give the seeded disposable API real credentials, an enabled login path and an
    enabled scheduler. Only assignments made before `app.config` is imported take effect.
    """
    source = (Path(__file__).resolve().parents[1] / "scripts" / "run_e2e_api.py").read_text(encoding="utf-8")
    first_settings_import = source.index("from app.config import")
    preamble = source[:first_settings_import]
    for name in ("DHIS2_ENABLED", "DHIS2_LOGIN_ENABLED", "SYNC_ENABLED"):
        assert f'os.environ["{name}"] = "false"' in preamble, name
        assert f'os.environ.setdefault("{name}"' not in source, f"{name} must not be overridable"
    for name in ("DHIS2_BASE_URL", "DHIS2_USERNAME", "DHIS2_PASSWORD", "DHIS2_PASSWORD_B64"):
        assert f'os.environ["{name}"] = ""' in preamble, name

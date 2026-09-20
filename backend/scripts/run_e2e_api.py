"""Launch a disposable SQLite API for frontend end-to-end smoke tests."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DB_PATH = ROOT / "e2e_hpip.sqlite"
if DB_PATH.exists():
    DB_PATH.unlink()

os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{DB_PATH.as_posix()}"
os.environ["SEED_DEV_DATA"] = "true"
os.environ["APP_ENV"] = "development"
os.environ["AUTH_SECRET"] = "e2e-secret-value-that-is-32-chars-minxx"
os.environ["AUTH_COOKIE_SECURE"] = "false"
os.environ["WEB_ORIGIN"] = "http://localhost:3000"
# Explicit development gates for the disposable end-to-end API (no Redis or worker process).
os.environ["EXPORT_EAGER"] = "true"
os.environ["RATE_LIMIT_BACKEND"] = "memory"
# This harness seeds synthetic users and observations, so it must never inherit a developer's
# gitignored live-DHIS2 configuration from the repository-root .env: the seeded run would then
# hold real credentials and could reach the live instance through a sync job. Set, not
# setdefault, so the disposable API is offline whatever the surrounding environment says.
os.environ["DHIS2_ENABLED"] = "false"
os.environ["DHIS2_LOGIN_ENABLED"] = "false"
os.environ["SYNC_ENABLED"] = "false"
# Clear the connection details too, so the synthetic process cannot reach the live instance even
# if a future code path forgets to check the gates above.
os.environ["DHIS2_BASE_URL"] = ""
os.environ["DHIS2_USERNAME"] = ""
os.environ["DHIS2_PASSWORD"] = ""
os.environ["DHIS2_PASSWORD_B64"] = ""
os.environ.setdefault("EXPORT_DIR", str(ROOT / "e2e_export_artifacts"))

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db.session import get_engine, reset_engine  # noqa: E402
from app.services.demo_data import seed_demo_analytics  # noqa: E402
from app.services.seed import seed_reference_data  # noqa: E402

get_settings.cache_clear()
reset_engine()
command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
settings = get_settings()
session = Session(get_engine())
try:
    seed_reference_data(session, settings.seed_password)
    # Synthetic demonstration analytics so the dashboards render populated, coloured screens.
    # Development/test only; the facility catchment, sub-county geometry and pre-FY2024/25 periods
    # are deliberately left empty so the honest-missing states stay visible.
    seed_demo_analytics(session, settings=settings)
    session.commit()
finally:
    session.close()

import uvicorn  # noqa: E402

uvicorn.run("app.main:app", host="127.0.0.1", port=8010, log_level="warning")

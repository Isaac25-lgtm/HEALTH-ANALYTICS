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
os.environ.setdefault("EXPORT_DIR", str(ROOT / "e2e_export_artifacts"))

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db.session import get_engine, reset_engine  # noqa: E402
from app.services.seed import seed_reference_data  # noqa: E402

get_settings.cache_clear()
reset_engine()
command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
settings = get_settings()
session = Session(get_engine())
try:
    seed_reference_data(session, settings.seed_password)
    session.commit()
finally:
    session.close()

import uvicorn  # noqa: E402

uvicorn.run("app.main:app", host="127.0.0.1", port=8010, log_level="warning")

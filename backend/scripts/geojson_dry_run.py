"""Dry-run owner-supplied GeoJSON against the synthetic geography master."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))

DB_PATH = ROOT / "geojson_dryrun.sqlite"
if DB_PATH.exists():
    DB_PATH.unlink()

os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{DB_PATH.as_posix()}"
os.environ["SEED_DEV_DATA"] = "true"
os.environ["APP_ENV"] = "development"
os.environ["AUTH_SECRET"] = "dryrun-secret-value-that-is-32-chars-min"

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db.session import get_engine, reset_engine  # noqa: E402
from app.services.geometry import prepare_geometry_import  # noqa: E402
from app.services.seed import seed_reference_data  # noqa: E402

get_settings.cache_clear()
reset_engine()
command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
session = Session(get_engine())
try:
    seed_reference_data(session, get_settings().seed_password)
    session.commit()
    reports = []
    jobs = [
        (REPO / "UGANDA_DISTRICT.json", "district"),
        (REPO / "UGANDA_SUBCOUNTIES.json", "sub_county"),
    ]
    for path, level in jobs:
        plan = prepare_geometry_import(session, path, level)
        reports.append({"mode": "dry_run", "applied": False, **plan.summary()})
    output = {
        "applied": False,
        "blocked_reason": (
            "Production application remains blocked until the approved analytical hierarchy, "
            "feature-to-org-unit mappings, and effective date are supplied to a manage_mappings user."
        ),
        "reports": reports,
    }
    report_path = REPO / "docs" / "architecture" / "GEOJSON_DRY_RUN.json"
    report_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in output.items() if key != "reports"} | {
        "report_path": str(report_path),
        "summaries": [
            {
                "source_file": item["source_file"],
                "level_type": item["level_type"],
                "total_features": item["total_features"],
                "matched_features": item["matched_features"],
                "unmatched_count": item["unmatched_count"],
                "ambiguous_count": item["ambiguous_count"],
                "invalid_count": item["invalid_count"],
            }
            for item in reports
        ],
    }, indent=2))
finally:
    session.close()
    reset_engine()
    try:
        DB_PATH.unlink(missing_ok=True)
    except PermissionError:
        pass

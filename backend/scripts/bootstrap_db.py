"""Apply migrations and optionally seed synthetic development users."""

import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.db.session import get_engine  # noqa: E402
from app.services.seed import seed_reference_data  # noqa: E402


def run_upgrade() -> None:
    cfg = Config(str(ROOT / "alembic.ini"))
    command.upgrade(cfg, "head")


def seed() -> None:
    settings = get_settings()
    engine = get_engine()
    session = Session(engine)
    try:
        seed_reference_data(session, settings.seed_password)
        session.commit()
    finally:
        session.close()


if __name__ == "__main__":
    run_upgrade()
    settings = get_settings()
    if settings.seed_dev_data and not settings.is_production:
        seed()
        print("Phase 1 schema applied and synthetic development users seeded.")
    else:
        print("Phase 1 schema applied. Development seed skipped.")

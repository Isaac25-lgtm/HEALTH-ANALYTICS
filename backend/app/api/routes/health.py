from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import Settings, get_settings, validate_runtime_settings
from app.db.session import get_db
from app.integrations.dhis2 import dhis2_readiness_status
from app.schemas.api import HealthResponse, ReadyResponse
from app.services.queue_health import broker_status, redis_status
from app.version import PHASE

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service="hpip-api",
        phase=PHASE,
    )


@router.get("/ready", response_model=ReadyResponse)
def ready(
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ReadyResponse:
    config_errors = validate_runtime_settings(settings)
    try:
        session.execute(text("SELECT 1"))
        database = "ok"
        db_ok = True
    except Exception:  # noqa: BLE001
        database = "unavailable"
        db_ok = False
    dhis2 = dhis2_readiness_status()
    queue = broker_status(settings)
    redis = redis_status(settings.redis_url) if settings.rate_limit_backend.strip().lower() == "redis" else "not_used"
    queue_ok = queue in {"ok", "in_memory"} or (settings.is_dev_or_test and queue == "unconfigured")
    redis_ok = redis in {"ok", "not_used"} or (settings.is_dev_or_test and redis == "unconfigured")
    status = "ok" if db_ok and not config_errors and queue_ok and redis_ok else "degraded"
    return ReadyResponse(
        status=status,
        database=database,
        dhis2=dhis2,
        queue=queue,
        redis=redis,
        config_errors=config_errors,
    )

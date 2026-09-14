from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, raise_authz
from app.config import get_settings, validate_runtime_settings
from app.db.session import get_db
from app.domain.enums import ActionPermission, JobStatus
from app.integrations.dhis2 import dhis2_readiness_status
from app.models import ExportJob, User
from app.services.authorization import AuthorizationError, require_action
from app.services.queue_health import broker_status, redis_status, worker_status

router = APIRouter(prefix="/ops", tags=["operations"])


@router.get("/status")
def ops_status(
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    try:
        require_action(session, user, ActionPermission.MANAGE_USERS)
    except AuthorizationError as error:
        raise_authz(error)
    settings = get_settings()
    try:
        session.execute(text("SELECT 1"))
        database = "ok"
    except Exception:
        database = "unavailable"
    counts = dict(
        session.execute(select(ExportJob.status, func.count()).group_by(ExportJob.status)).all()
    )
    failed_permanent = session.scalar(
        select(func.count())
        .select_from(ExportJob)
        .where(ExportJob.status == JobStatus.FAILED.value, ExportJob.active_key.is_(None))
    )
    return {
        "database": database,
        "dhis2": dhis2_readiness_status(),
        "ai_enabled": settings.ai_enabled,
        "ai_provider_configured": bool(settings.ai_api_key and settings.ai_base_url),
        "sync_execution": settings.sync_execution,
        "export_execution": "eager" if settings.export_eager else "queue",
        "queue": broker_status(settings),
        "redis": redis_status(settings.redis_url),
        "rate_limit_backend": settings.rate_limit_backend,
        "workers": worker_status() if not settings.export_eager else {"status": "not_used", "responding_workers": 0},
        "export_jobs": {
            "by_status": {str(key): int(value) for key, value in counts.items()},
            "failed_permanently": int(failed_permanent or 0),
        },
        "formula_undated_policy": settings.undated_formula_policy,
        "config_errors": validate_runtime_settings(settings),
        "secrets_exposed": False,
    }

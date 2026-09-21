from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, raise_authz
from app.config import get_settings, validate_runtime_settings
from app.db.session import get_db
from app.domain.enums import ActionPermission, JobStatus
from app.integrations.dhis2 import dhis2_readiness_status
from app.models import (
    ExportJob,
    FreshnessSnapshot,
    Geometry,
    IndicatorVersion,
    OrgUnit,
    OrgUnitMapping,
    PopulationImportBatch,
    PopulationValue,
    PopulationVersion,
    Programme,
    SourceMapping,
    SyncJob,
    User,
)
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
    org_by_level = dict(
        session.execute(
            select(OrgUnit.level_type, func.count())
            .where(OrgUnit.active.is_(True))
            .group_by(OrgUnit.level_type)
        ).all()
    )
    mapped_by_level = dict(
        session.execute(
            select(OrgUnit.level_type, func.count(func.distinct(OrgUnitMapping.org_unit_id)))
            .join(OrgUnitMapping, OrgUnitMapping.org_unit_id == OrgUnit.id)
            .where(OrgUnitMapping.source_system == "dhis2")
            .group_by(OrgUnit.level_type)
        ).all()
    )
    source_mapping_rows = session.execute(
        select(Programme.code, SourceMapping.mapping_version, func.count())
        .join(SourceMapping, SourceMapping.programme_id == Programme.id)
        .where(SourceMapping.enabled.is_(True))
        .group_by(Programme.code, SourceMapping.mapping_version)
        .order_by(Programme.code, SourceMapping.mapping_version)
    ).all()
    geometry_by_level = dict(
        session.execute(
            select(OrgUnit.level_type, func.count())
            .join(Geometry, Geometry.org_unit_id == OrgUnit.id)
            .where(Geometry.valid_to.is_(None))
            .group_by(OrgUnit.level_type)
        ).all()
    )
    population_batches = dict(
        session.execute(
            select(PopulationImportBatch.status, func.count()).group_by(PopulationImportBatch.status)
        ).all()
    )
    population_versions = dict(
        session.execute(
            select(PopulationVersion.approval_status, func.count()).group_by(
                PopulationVersion.approval_status
            )
        ).all()
    )
    sync_counts = dict(
        session.execute(select(SyncJob.status, func.count()).group_by(SyncJob.status)).all()
    )
    freshness = list(
        session.scalars(select(FreshnessSnapshot).order_by(FreshnessSnapshot.connector)).all()
    )
    formula_total = int(session.scalar(select(func.count()).select_from(IndicatorVersion)) or 0)
    formula_dated = int(
        session.scalar(
            select(func.count())
            .select_from(IndicatorVersion)
            .where(IndicatorVersion.valid_from.is_not(None))
        )
        or 0
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
        "configuration": {
            "org_units": {
                "total": sum(int(value) for value in org_by_level.values()),
                "by_level": {str(key): int(value) for key, value in org_by_level.items()},
                "dhis2_mapped_by_level": {
                    str(key): int(value) for key, value in mapped_by_level.items()
                },
            },
            "source_mappings": [
                {"programme": code, "version": version, "enabled_rows": int(count)}
                for code, version, count in source_mapping_rows
            ],
            "population": {
                "staging_batches_by_status": {
                    str(key): int(value) for key, value in population_batches.items()
                },
                "versions_by_approval": {
                    str(key): int(value) for key, value in population_versions.items()
                },
                "value_rows": int(
                    session.scalar(select(func.count()).select_from(PopulationValue)) or 0
                ),
            },
            "boundaries": {
                "current_by_level": {
                    str(key): int(value) for key, value in geometry_by_level.items()
                }
            },
            "formulas": {
                "total_versions": formula_total,
                "dated_versions": formula_dated,
                "undated_versions": formula_total - formula_dated,
            },
        },
        "sync_jobs": {
            "by_status": {str(key): int(value) for key, value in sync_counts.items()},
            "freshness": [
                {
                    "connector": row.connector,
                    "status": row.status,
                    "last_success_at": row.last_success_at.isoformat()
                    if row.last_success_at
                    else None,
                    "source_freshness_at": row.source_freshness_at.isoformat()
                    if row.source_freshness_at
                    else None,
                }
                for row in freshness
            ],
        },
        "formula_undated_policy": settings.undated_formula_policy,
        "config_errors": validate_runtime_settings(settings),
        "secrets_exposed": False,
    }

from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import false, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, parse_uuid, raise_authz
from app.config import get_settings
from app.db.session import get_db
from app.domain.enums import ActionPermission, ConnectorType, JobStatus
from app.domain.modules import MODULE_PROGRAMME
from app.domain.periods import PeriodError, parse_period
from app.integrations.dhis2.gates import extraction_blocked_reason
from app.models import FreshnessSnapshot, Programme, SourceMapping, SyncJob, User
from app.schemas.api import DashboardRefreshRequest, SyncJobRequest, SyncJobResponse
from app.services.authorization import (
    AuthorizationError,
    authorised_org_unit_ids,
    authorised_programme_ids,
    require_action,
    require_org_unit_access,
    require_programme_access,
)
from app.services.mapping_coverage import evaluate_coverage
from app.services.sync import (
    SyncDispatchError,
    dispatch_sync_job,
    enqueue_sync_job,
    execute_sync_job,
    should_run_eager,
)

router = APIRouter(prefix="/sync", tags=["sync"])


def _job(row: SyncJob) -> SyncJobResponse:
    return SyncJobResponse(
        id=row.id,
        job_type=row.job_type,
        status=row.status,
        requested_count=row.requested_count,
        received_count=row.received_count,
        stored_count=row.stored_count,
        rejected_count=row.rejected_count,
        flagged_count=row.flagged_count,
        retry_count=row.retry_count,
        error_code=row.error_code,
        error_message=row.error_message,
        source_freshness_at=row.source_freshness_at.isoformat() if row.source_freshness_at else None,
    )


def _validate_event_window(body: SyncJobRequest, period_end: date) -> None:
    if body.event_window_end is None:
        return
    if body.job_type != ConnectorType.TRACKER:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "event_window_not_supported",
                "message": "An event window end applies only to Tracker synchronisation jobs.",
            },
        )
    if body.event_window_end < period_end or body.event_window_end > datetime.now(UTC).date():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "invalid_event_window",
                "message": "The event window end must fall between the period end and today.",
            },
        )


def _visible_jobs(session: Session, user: User):
    query = select(SyncJob).order_by(SyncJob.created_at.desc())
    if user.is_system_admin:
        return session.scalars(query).all()
    geo_ids = authorised_org_unit_ids(session, user)
    prog_ids = authorised_programme_ids(session, user)
    if not geo_ids or not prog_ids:
        return session.scalars(query.where(false())).all()
    query = query.where(
        SyncJob.org_unit_id.in_(geo_ids),
        SyncJob.programme_id.in_(prog_ids),
    )
    return session.scalars(query).all()


def _complete_mapping_version(
    session: Session,
    *,
    programme: Programme,
    as_of: date,
) -> str:
    versions = sorted(
        set(
            session.scalars(
                select(SourceMapping.mapping_version).where(
                    SourceMapping.programme_id == programme.id,
                    SourceMapping.enabled.is_(True),
                    SourceMapping.dhis2_item_uid.is_not(None),
                )
            ).all()
        )
    )
    reports = [
        evaluate_coverage(
            session,
            programme_id=programme.id,
            mapping_version=version,
            as_of=as_of,
        )
        for version in versions
    ]
    complete = [report.mapping_version for report in reports if report.complete]
    if len(complete) == 1:
        return complete[0]
    if len(complete) > 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "mapping_version_ambiguous",
                "message": (
                    "More than one complete mapping version is in force. Close the superseded "
                    "version's validity window before refreshing."
                ),
            },
        )
    best = max(reports, key=lambda report: len(report.resolved), default=None)
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={
            "code": "mapping_coverage_incomplete",
            "message": (
                f"No complete in-force source mapping exists for {programme.code}."
                + (
                    f" Best candidate {best.mapping_version!r} resolves "
                    f"{len(best.resolved)} of {len(best.required)} required source keys."
                    if best
                    else " No source-mapping version has been applied."
                )
            ),
        },
    )


def _dispatch_created_job(session: Session, job: SyncJob) -> SyncJob:
    session.commit()
    if should_run_eager():
        job = execute_sync_job(session, job.id)
        session.commit()
        return job
    try:
        dispatch_sync_job(job.id)
    except SyncDispatchError as exc:
        job.status = JobStatus.FAILED.value
        job.error_code = "sync_enqueue_failed"
        job.error_message = str(exc)
        job.finished_at = datetime.now(UTC)
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": job.error_code, "message": job.error_message},
        ) from exc
    session.refresh(job)
    return job


@router.get("/jobs", response_model=list[SyncJobResponse])
def list_jobs(
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[SyncJobResponse]:
    try:
        require_action(session, user, ActionPermission.MANAGE_SYNC)
    except AuthorizationError as error:
        raise_authz(error)
    return [_job(row) for row in _visible_jobs(session, user)]


@router.get("/jobs/{job_id}", response_model=SyncJobResponse)
def get_job(
    job_id: str,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SyncJobResponse:
    try:
        require_action(session, user, ActionPermission.MANAGE_SYNC)
        row = session.get(SyncJob, parse_uuid(job_id, "job_id"))
        if row is None:
            raise AuthorizationError("not_found", "Sync job not found.")
        if not user.is_system_admin:
            geo_ids = authorised_org_unit_ids(session, user)
            prog_ids = authorised_programme_ids(session, user)
            if row.org_unit_id is None or row.org_unit_id not in geo_ids:
                raise AuthorizationError("forbidden_geography", "Sync job is outside authorised geography.")
            if row.programme_id is None or row.programme_id not in prog_ids:
                raise AuthorizationError("forbidden_programme", "Sync job is outside authorised programme scope.")
    except AuthorizationError as error:
        raise_authz(error)
    return _job(row)


@router.post("/jobs/{job_id}/cancel", response_model=SyncJobResponse, status_code=202)
def cancel_job(
    job_id: str,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SyncJobResponse:
    try:
        require_action(session, user, ActionPermission.MANAGE_SYNC)
        row = session.get(SyncJob, parse_uuid(job_id, "job_id"))
        if row is None:
            raise AuthorizationError("not_found", "Sync job not found.")
        if not user.is_system_admin:
            if row.org_unit_id not in authorised_org_unit_ids(session, user):
                raise AuthorizationError(
                    "forbidden_geography", "Sync job is outside authorised geography."
                )
            if row.programme_id not in authorised_programme_ids(session, user):
                raise AuthorizationError(
                    "forbidden_programme", "Sync job is outside authorised programme scope."
                )
    except AuthorizationError as error:
        raise_authz(error)
    if row.status in {JobStatus.QUEUED.value, JobStatus.RUNNING.value}:
        row.cancelled = True
        if row.status == JobStatus.QUEUED.value:
            row.status = JobStatus.CANCELLED.value
            row.finished_at = datetime.now(UTC)
        session.commit()
        session.refresh(row)
    return _job(row)


@router.post("/jobs", response_model=SyncJobResponse, status_code=202)
def create_job(
    body: SyncJobRequest,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SyncJobResponse:
    try:
        spec = parse_period(body.period)
        require_action(session, user, ActionPermission.MANAGE_SYNC)
        unit = require_org_unit_access(session, user, body.org_unit_id)
        require_programme_access(session, user, body.programme.value)
    except PeriodError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_period", "message": str(exc)},
        ) from exc
    except AuthorizationError as error:
        raise_authz(error)
    _validate_event_window(body, spec.end)
    programme = session.scalar(select(Programme).where(Programme.code == body.programme.value))
    if programme is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "unknown_programme", "message": "Programme is not configured."},
        )
    if body.job_type == ConnectorType.AGGREGATE:
        report = evaluate_coverage(
            session,
            programme_id=programme.id,
            mapping_version=body.mapping_version,
            as_of=spec.start,
        )
        if not report.complete:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "mapping_coverage_incomplete",
                    "message": (
                        f"Mapping version {body.mapping_version!r} resolves {len(report.resolved)} "
                        f"of {len(report.required)} required {programme.code} source keys."
                    ),
                },
            )
    # The request is well-formed and authorised; the remaining question is whether this
    # deployment may contact DHIS2 at all. Fail before a job row exists, so a disabled
    # deployment never accumulates queued work that can never run.
    blocked = extraction_blocked_reason(get_settings())
    if blocked is not None:
        code, message = blocked
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": code, "message": message},
        )
    job = enqueue_sync_job(
        session,
        org_unit=unit,
        periods=[body.period],
        user=user,
        job_type=body.job_type.value,
        programme_id=programme.id if programme else None,
        mapping_version=body.mapping_version,
        idempotency_key=body.idempotency_key,
        window_end=body.event_window_end,
    )
    return _job(_dispatch_created_job(session, job))


@router.post("/refresh", response_model=SyncJobResponse, status_code=202)
def refresh_dashboard_source(
    body: DashboardRefreshRequest,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SyncJobResponse:
    """Refresh a dashboard without allowing the browser to select DHIS2 identifiers.

    MPDSR is deliberately excluded until its event-date semantics and mappings are approved.
    """
    try:
        spec = parse_period(body.period)
        require_action(session, user, ActionPermission.MANAGE_SYNC)
        unit = require_org_unit_access(session, user, body.org_unit_id)
        programme_code = MODULE_PROGRAMME.get(body.module)
        if programme_code is None:
            raise AuthorizationError("invalid_input", "The analytical module is not recognised.")
        require_programme_access(session, user, programme_code)
    except PeriodError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_period", "message": str(exc)},
        ) from exc
    except AuthorizationError as error:
        raise_authz(error)
    if body.module == "mpdsr":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "mpdsr_semantics_pending",
                "message": "MPDSR refresh remains blocked until the owner approves event-date semantics.",
            },
        )
    blocked = extraction_blocked_reason(get_settings())
    if blocked is not None:
        code, message = blocked
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": code, "message": message},
        )
    programme = session.scalar(
        select(Programme).where(Programme.code == programme_code, Programme.active.is_(True))
    )
    if programme is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "unknown_programme", "message": "Programme is not configured."},
        )
    mapping_version = _complete_mapping_version(session, programme=programme, as_of=spec.start)
    job = enqueue_sync_job(
        session,
        org_unit=unit,
        periods=[body.period],
        user=user,
        job_type=ConnectorType.AGGREGATE.value,
        programme_id=programme.id,
        mapping_version=mapping_version,
        idempotency_key=body.idempotency_key,
    )
    return _job(_dispatch_created_job(session, job))


@router.get("/freshness")
def freshness(
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    try:
        require_action(session, user, ActionPermission.VIEW)
    except AuthorizationError as error:
        raise_authz(error)
    rows = session.scalars(select(FreshnessSnapshot)).all()
    return [
        {
            "connector": row.connector,
            "status": row.status,
            "last_success_at": row.last_success_at.isoformat() if row.last_success_at else None,
            "source_freshness_at": row.source_freshness_at.isoformat() if row.source_freshness_at else None,
            "lag_seconds": row.lag_seconds,
            "last_success_sync_job_id": str(row.sync_job_id) if row.sync_job_id else None,
            "last_attempt": (row.detail or {}).get("last_attempt"),
        }
        for row in rows
    ]

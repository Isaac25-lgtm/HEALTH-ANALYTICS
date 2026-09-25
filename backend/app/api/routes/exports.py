from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, parse_uuid, raise_authz, require_write
from app.db.session import get_db
from app.domain.enums import ActionPermission, JobStatus, ProgrammeCode
from app.domain.exports import export_label
from app.domain.modules import MODULE_PROGRAMME
from app.models import ExportJob, User
from app.schemas.api import ExportAcceptedResponse
from app.services import artifact_store
from app.services.audit import write_audit
from app.services.authorization import (
    AuthorizationError,
    require_action,
    require_org_unit_access,
    require_programme_access,
)
from app.services.export_jobs import (
    DISPATCH_ERROR_CODES,
    SAFE_ERROR_MESSAGES,
    ExportSubmission,
    ExportUnavailable,
    export_job_payload,
    request_export_retry,
    start_export_job,
    submit_export,
)

router = APIRouter(prefix="/exports", tags=["exports"])


class ExportRequest(BaseModel):
    org_unit_id: str
    period: str
    module: str | None = None
    comparison_period: str | None = None
    analysis_snapshot_id: str | None = None
    view_hash: str | None = None


def _respond(submission: ExportSubmission, job: ExportJob) -> ExportAcceptedResponse | JSONResponse:
    label = export_label(job.export_type)
    payload = export_job_payload(job)
    if job.status == JobStatus.FAILED.value and job.error_code in DISPATCH_ERROR_CODES:
        # Honest representation: the job exists and is committed, but no worker has it.
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "detail": {
                    "code": job.error_code,
                    "message": SAFE_ERROR_MESSAGES[job.error_code],
                    "job_id": str(job.id),
                    "retryable": payload["retryable"],
                }
            },
        )
    if job.status == JobStatus.SUCCEEDED.value:
        message = f"{label} generated from snapshot {job.analysis_snapshot_id}."
    elif job.status == JobStatus.FAILED.value:
        message = f"{label} failed for snapshot {job.analysis_snapshot_id}."
    else:
        message = f"{label} queued from snapshot {job.analysis_snapshot_id}."
    return ExportAcceptedResponse(
        job_id=job.id,
        status=job.status,
        message=message,
        reused=submission.reused,
        dispatch_state=job.dispatch_state,
        error_code=job.error_code,
        retryable=payload["retryable"],
        retry_scheduled=payload["retry_scheduled"],
        attempt_count=job.attempt_count,
    )


def _create(
    request: Request,
    body: ExportRequest,
    export_type: str,
    session: Session,
    user: User,
) -> ExportAcceptedResponse | JSONResponse:
    try:
        submission = submit_export(
            session,
            user=user,
            export_type=export_type,
            org_unit_id=parse_uuid(body.org_unit_id, "org_unit_id"),
            period=body.period,
            module=body.module,
            comparison_period=body.comparison_period,
            analysis_snapshot_id=UUID(body.analysis_snapshot_id) if body.analysis_snapshot_id else None,
            view_hash=body.view_hash,
        )
    except ExportUnavailable as error:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": error.code, "message": str(error)},
        ) from error
    except AuthorizationError as error:
        session.rollback()
        raise_authz(error)
    job = submission.job
    write_audit(
        session,
        actor_user_id=user.id,
        action=f"export_{export_type}_requested",
        resource_type="export_job",
        resource_id=str(job.id),
        after={
            "org_unit_id": body.org_unit_id,
            "period": body.period,
            "module": job.module,
            "analysis_snapshot_id": str(job.analysis_snapshot_id),
            "reused": submission.reused,
            "dispatch": submission.needs_dispatch,
        },
        ip_address=request.client.host if request.client else None,
    )
    # The job and its audit record are durable before any worker can see the job.
    session.commit()
    if submission.needs_dispatch:
        job = start_export_job(session, job.id)
    else:
        session.refresh(job)
    return _respond(submission, job)


@router.post("/excel", response_model=ExportAcceptedResponse, status_code=202)
def queue_excel_export(
    request: Request,
    body: ExportRequest | None = None,
    org_unit_id: str | None = None,
    period: str = "FY2024/25",
    module: str | None = None,
    programme: str | None = None,
    session: Session = Depends(require_write),
    user: User = Depends(get_current_user),
) -> ExportAcceptedResponse | JSONResponse:
    payload = body or ExportRequest(org_unit_id=org_unit_id or "", period=period, module=module)
    if not payload.org_unit_id:
        raise HTTPException(status_code=422, detail={"code": "invalid_input", "message": "org_unit_id is required."})
    if programme == ProgrammeCode.EPI.value and not payload.module:
        payload = payload.model_copy(update={"module": "immunization"})
    return _create(request, payload, "excel", session, user)


@router.post("/powerpoint", response_model=ExportAcceptedResponse, status_code=202)
def queue_powerpoint(
    request: Request,
    body: ExportRequest,
    session: Session = Depends(require_write),
    user: User = Depends(get_current_user),
) -> ExportAcceptedResponse | JSONResponse:
    return _create(request, body, "powerpoint", session, user)


@router.post("/report", response_model=ExportAcceptedResponse, status_code=202)
def queue_report(
    request: Request,
    body: ExportRequest,
    session: Session = Depends(require_write),
    user: User = Depends(get_current_user),
) -> ExportAcceptedResponse | JSONResponse:
    return _create(request, body, "report", session, user)


@router.post("/pdf", response_model=ExportAcceptedResponse, status_code=202)
def queue_pdf(
    request: Request,
    body: ExportRequest,
    session: Session = Depends(require_write),
    user: User = Depends(get_current_user),
) -> ExportAcceptedResponse | JSONResponse:
    return _create(request, body, "pdf", session, user)


@router.post("/word", response_model=ExportAcceptedResponse, status_code=202)
def queue_word(
    request: Request,
    body: ExportRequest,
    session: Session = Depends(require_write),
    user: User = Depends(get_current_user),
) -> ExportAcceptedResponse | JSONResponse:
    return _create(request, body, "word", session, user)


@router.get("/jobs")
def list_export_jobs(
    limit: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """The caller's own export history, newest first. Read-only."""
    rows = session.scalars(
        select(ExportJob)
        .where(ExportJob.user_id == user.id)
        .order_by(ExportJob.created_at.desc(), ExportJob.id.desc())
        .limit(limit)
    ).all()
    return {"jobs": [export_job_payload(row, session) for row in rows]}


@router.get("/jobs/{job_id}")
def get_export_job(
    job_id: str,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    job = session.get(ExportJob, parse_uuid(job_id, "job_id"))
    if job is None or job.user_id != user.id:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Export job was not found."})
    return export_job_payload(job, session)


@router.post("/jobs/{job_id}/retry", response_model=ExportAcceptedResponse, status_code=202)
def retry_export_job(
    request: Request,
    job_id: str,
    session: Session = Depends(require_write),
    user: User = Depends(get_current_user),
) -> ExportAcceptedResponse | JSONResponse:
    try:
        submission = request_export_retry(session, user=user, job_id=parse_uuid(job_id, "job_id"))
    except AuthorizationError as error:
        session.rollback()
        raise_authz(error)
    job = submission.job
    write_audit(
        session,
        actor_user_id=user.id,
        action="export_retry_requested",
        resource_type="export_job",
        resource_id=str(job.id),
        after={"attempt_count": job.attempt_count, "export_type": job.export_type},
        ip_address=request.client.host if request.client else None,
    )
    session.commit()
    job = start_export_job(session, job.id)
    return _respond(submission, job)


@router.post("/jobs/{job_id}/download")
def download_export(
    job_id: str,
    transport: str | None = Query(default=None, pattern="^blob$"),
    session: Session = Depends(require_write),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Download writes an access audit record, so it is a CSRF-protected POST, never a GET.

    Permissions are re-checked on every download, and an expired artifact is reported as
    ``artifact_expired`` (HTTP 410) rather than an unexplained 404.

    ``transport=blob`` is for the web client, which saves the bytes itself: the file is sent as
    ``application/octet-stream`` with its name in ``X-Export-Filename``, so a browser's own PDF
    handler cannot intercept the response and hand the page an empty body.
    """
    job = session.get(ExportJob, parse_uuid(job_id, "job_id"))
    if job is None or job.user_id != user.id:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Export job was not found."})
    try:
        require_action(session, user, ActionPermission.EXPORT)
        if job.org_unit_id:
            require_org_unit_access(session, user, job.org_unit_id)
        if job.module and job.module in MODULE_PROGRAMME:
            require_programme_access(session, user, MODULE_PROGRAMME[job.module])
    except AuthorizationError as error:
        session.rollback()
        raise_authz(error)
    if job.status != JobStatus.SUCCEEDED.value:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "export_not_ready",
                "message": "This export has not finished successfully.",
                "status": job.status,
            },
        )
    try:
        payload = artifact_store.load(session, job)
    except artifact_store.ArtifactError as error:
        status_code = 410 if error.code == artifact_store.ARTIFACT_EXPIRED else 409
        raise HTTPException(
            status_code=status_code,
            detail={
                "code": error.code,
                "message": str(error),
                "job_id": str(job.id),
                "checksum": job.checksum,
                "artifact_expires_at": job.artifact_expires_at.isoformat() if job.artifact_expires_at else None,
            },
        ) from None
    write_audit(
        session,
        actor_user_id=user.id,
        action="export_downloaded",
        resource_type="export_job",
        resource_id=str(job.id),
        after={"checksum": job.checksum, "export_type": job.export_type, "storage": job.artifact_storage},
        commit=True,
    )
    if transport == "blob":
        # No Content-Disposition: Chrome treats an attachment named *.pdf as a PDF download even
        # for fetch(), and gives the page an empty response. The client names the file itself.
        return StreamingResponse(
            payload.chunks(),
            media_type="application/octet-stream",
            headers={"X-Export-Filename": payload.filename, "Content-Length": str(payload.size_bytes)},
        )
    return StreamingResponse(
        payload.chunks(),
        media_type=payload.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{payload.filename}"',
            "Content-Length": str(payload.size_bytes),
        },
    )


@router.post("/mpdsr-linelist", response_model=ExportAcceptedResponse, status_code=202)
def queue_mpdsr_linelist(
    request: Request,
    org_unit_id: str,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ExportAcceptedResponse:
    try:
        require_action(session, user, ActionPermission.EXPORT_MPDSR_LINELIST)
        require_org_unit_access(session, user, parse_uuid(org_unit_id, "org_unit_id"))
    except AuthorizationError as error:
        raise_authz(error)
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={
            "code": "mpdsr_linelist_blocked",
            "message": (
                "Identifying MPDSR line-list export remains blocked until disclosure governance "
                "and semantic field mappings are supplied. Use aggregate MPDSR exports instead."
            ),
        },
    )

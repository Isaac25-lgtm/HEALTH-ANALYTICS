from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, parse_uuid, raise_authz, require_write
from app.models import User
from app.services.ai_gateway import run_ai_task
from app.services.audit import write_audit
from app.services.authorization import AuthorizationError

router = APIRouter(prefix="/ai", tags=["ai"])


class AiRequestBody(BaseModel):
    org_unit_id: str
    period: str
    module: str | None = None
    comparison_period: str | None = None
    indicator_code: str | None = None
    question: str | None = Field(default=None, max_length=500)
    analysis_snapshot_id: str | None = None
    view_hash: str | None = None


def _run(request: Request, body: AiRequestBody, task: str, session: Session, user: User) -> dict:
    try:
        result = run_ai_task(
            session,
            user=user,
            org_unit_id=parse_uuid(body.org_unit_id, "org_unit_id"),
            period=body.period,
            module=body.module,
            task=task,
            question=body.question,
            indicator_code=body.indicator_code,
            comparison_period=body.comparison_period,
            analysis_snapshot_id=UUID(body.analysis_snapshot_id) if body.analysis_snapshot_id else None,
            view_hash=body.view_hash,
        )
    except AuthorizationError as error:
        raise_authz(error)
    write_audit(
        session,
        actor_user_id=user.id,
        action=f"ai_{task}",
        resource_type="ai_request",
        resource_id=result["ai_request_id"],
        after={"task": task, "module": body.module, "fallback_used": result["fallback_used"]},
        ip_address=request.client.host if request.client else None,
        commit=True,
    )
    return result


@router.post("/findings")
def ai_findings(
    request: Request,
    body: AiRequestBody,
    session: Session = Depends(require_write),
    user: User = Depends(get_current_user),
) -> dict:
    return _run(request, body, "findings", session, user)


@router.post("/explain")
def ai_explain(
    request: Request,
    body: AiRequestBody,
    session: Session = Depends(require_write),
    user: User = Depends(get_current_user),
) -> dict:
    return _run(request, body, "explain", session, user)


@router.post("/ask")
def ai_ask(
    request: Request,
    body: AiRequestBody,
    session: Session = Depends(require_write),
    user: User = Depends(get_current_user),
) -> dict:
    return _run(request, body, "ask", session, user)


@router.post("/report")
def ai_report(
    request: Request,
    body: AiRequestBody,
    session: Session = Depends(require_write),
    user: User = Depends(get_current_user),
) -> dict:
    return _run(request, body, "report", session, user)

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, raise_authz, require_write
from app.domain.periods import PeriodError
from app.models import User
from app.schemas.api import DashboardQueryRequest
from app.services.analysis import find_request_snapshot, load_snapshot, request_matches, snapshot_response
from app.services.authorization import AuthorizationError
from app.services.dashboard import build_dashboard

router = APIRouter(prefix="/analytics/dashboard", tags=["dashboard"])


def _reuse(session: Session, user: User, body: DashboardQueryRequest) -> dict | None:
    if not body.request_key:
        return None
    existing = find_request_snapshot(session, user=user, request_key=body.request_key)
    if existing is None:
        return None
    if not request_matches(
        existing,
        org_unit_id=body.org_unit_id,
        period=body.period,
        module=body.module,
        comparison_period=body.comparison_period,
        selected_indicator=body.selected_indicator,
    ):
        raise AuthorizationError(
            "snapshot_conflict",
            "This request key was already used for a different analytical request.",
        )
    return snapshot_response(load_snapshot(session, user=user, snapshot_id=existing.id), reused=True)


@router.post("/query", status_code=status.HTTP_201_CREATED)
def query_dashboard(
    body: DashboardQueryRequest,
    response: Response,
    session: Session = Depends(require_write),
    user: User = Depends(get_current_user),
) -> dict:
    """Run the analytical calculation and commit one snapshot.

    Analytical execution is a state-changing, CSRF-protected POST. A repeated submission
    with the same ``request_key`` returns the committed snapshot instead of creating
    hidden duplicate runs. Read committed snapshots with GET /analysis-snapshots/{id}.
    """
    try:
        reused = _reuse(session, user, body)
        if reused is not None:
            response.status_code = status.HTTP_200_OK
            return reused
        dashboard = build_dashboard(
            session,
            user=user,
            org_unit_id=body.org_unit_id,
            period=body.period,
            module=body.module,
            comparison_period=body.comparison_period,
            selected_indicator=body.selected_indicator,
            request_key=body.request_key,
        )
        session.commit()
    except PeriodError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_period", "message": str(exc)},
        ) from exc
    except AuthorizationError as error:
        raise_authz(error)
    except IntegrityError:
        # A concurrent submission with the same request key committed first.
        session.rollback()
        try:
            reused = _reuse(session, user, body)
        except AuthorizationError as error:
            raise_authz(error)
        if reused is None:
            raise
        response.status_code = status.HTTP_200_OK
        return reused
    dashboard["snapshot_reused"] = False
    return dashboard

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, parse_uuid, raise_authz, require_write
from app.db.session import get_db
from app.domain.enums import ActionPermission
from app.domain.modules import MODULE_INDICATORS, MODULE_PROGRAMME
from app.domain.periods import PeriodError, parse_period
from app.models import User
from app.schemas.api import DashboardQueryRequest
from app.services.analysis import find_request_snapshot, load_snapshot, request_matches, snapshot_response
from app.services.authorization import (
    AuthorizationError,
    require_action,
    require_org_unit_access,
    require_programme_access,
)
from app.services.dashboard import FACILITY_JOBS_KEY, build_dashboard
from app.services.facility_data import facility_data_status, run_facility_job
from app.services.prepared_dashboard import find_prepared_dashboard

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
    background: BackgroundTasks,
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
        prepared = find_prepared_dashboard(
            session,
            user,
            org_unit_id=body.org_unit_id,
            period=body.period,
            module=body.module,
            comparison_period=body.comparison_period,
            selected_indicator=body.selected_indicator,
        )
        if prepared is not None:
            response.status_code = status.HTTP_200_OK
            return prepared
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
        for job_id in session.info.pop(FACILITY_JOBS_KEY, []):
            background.add_task(run_facility_job, job_id)
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


@router.get("/prepared")
def prepared_dashboard(
    org_unit_id: str,
    period: str,
    module: str | None = None,
    comparison_period: str | None = None,
    selected_indicator: str | None = None,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Read-only ready-product lookup; never creates a run, job or snapshot."""
    try:
        parse_period(period)
        unit = require_org_unit_access(session, user, parse_uuid(org_unit_id, "org_unit_id"), period=period)
        require_action(session, user, ActionPermission.VIEW)
        if module:
            if module not in MODULE_PROGRAMME:
                raise AuthorizationError("invalid_input", "Unknown module.")
            require_programme_access(session, user, MODULE_PROGRAMME[module])
        result = find_prepared_dashboard(
            session,
            user,
            org_unit_id=unit.id,
            period=period,
            module=module,
            comparison_period=comparison_period,
            selected_indicator=selected_indicator,
        )
        return {"ready": result is not None, "dashboard": result}
    except PeriodError as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_period", "message": str(exc)}) from exc
    except AuthorizationError as error:
        raise_authz(error)


@router.get("/facility-status")
def facility_status(
    org_unit_id: str,
    period: str,
    module: str = Query(default="anc"),
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Whether a district's on-demand facility figures are ready (D-068). Read-only."""
    if module not in MODULE_INDICATORS:
        raise HTTPException(status_code=422, detail={"code": "invalid_input", "message": "Unknown module."})
    try:
        require_action(session, user, ActionPermission.VIEW)
        require_programme_access(session, user, MODULE_PROGRAMME[module])
        unit = require_org_unit_access(session, user, parse_uuid(org_unit_id, "org_unit_id"), period=period)
        return facility_data_status(session, org_unit=unit, period=period, module=module).payload()
    except PeriodError as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_period", "message": str(exc)}) from exc
    except AuthorizationError as error:
        raise_authz(error)

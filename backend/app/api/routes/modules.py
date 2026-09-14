from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, raise_authz, require_write
from app.domain.modules import MODULE_INDICATORS
from app.domain.periods import PeriodError
from app.models import User
from app.schemas.api import ModuleQueryRequest
from app.services.authorization import AuthorizationError
from app.services.modules import evaluate_module

router = APIRouter(prefix="/analytics/modules", tags=["analytical-modules"])


@router.post("/{module}/query", status_code=status.HTTP_201_CREATED)
def query_module(
    module: str,
    body: ModuleQueryRequest,
    session: Session = Depends(require_write),
    user: User = Depends(get_current_user),
) -> dict:
    """Evaluate a module and commit its calculation runs. CSRF-protected; never a GET."""
    if module not in MODULE_INDICATORS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "unknown_module", "message": "Analytical module is not recognised."},
        )
    try:
        result = evaluate_module(
            session,
            user=user,
            org_unit_id=body.org_unit_id,
            period=body.period,
            module=module,
            comparison_period=body.comparison_period,
            include_children=body.include_children,
        )
        session.commit()
    except PeriodError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_period", "message": str(exc)},
        ) from exc
    except AuthorizationError as error:
        raise_authz(error)
    return result

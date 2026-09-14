from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, raise_authz
from app.db.session import get_db
from app.domain.enums import ActionPermission, ProgrammeCode
from app.models import User
from app.services.authorization import AuthorizationError, require_action, require_programme_access

router = APIRouter(prefix="/mpdsr", tags=["mpdsr"])


@router.get("/events")
def list_events(
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Operational event access is separated from ordinary MNCH programme view.

    Phase 2 stores minimised snapshots internally. This endpoint does not return
    raw event payloads. ACTIVE records must never count as completed.
    """
    try:
        require_action(session, user, ActionPermission.VIEW_MPDSR_EVENTS)
        require_programme_access(session, user, ProgrammeCode.MPDSR.value)
    except AuthorizationError as error:
        raise_authz(error)
    return {
        "events": [],
        "note": (
            "Raw event payloads are not exposed through this ordinary API. "
            "ACTIVE records must never count as completed."
        ),
    }

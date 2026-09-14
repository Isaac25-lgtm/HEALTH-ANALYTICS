from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, raise_authz
from app.db.session import get_db
from app.domain.enums import ActionPermission
from app.models import User
from app.services.audit import write_audit
from app.services.authorization import AuthorizationError, require_action

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/probe")
def admin_probe(
    request: Request,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Privileged probe used to verify admin permission and audit logging."""
    try:
        require_action(session, user, ActionPermission.MANAGE_USERS)
    except AuthorizationError as error:
        raise_authz(error)
    write_audit(
        session,
        actor_user_id=user.id,
        action="admin_probe",
        resource_type="admin",
        resource_id=str(user.id),
        ip_address=request.client.host if request.client else None,
        commit=True,
    )
    return {"status": "ok", "actor": user.username}

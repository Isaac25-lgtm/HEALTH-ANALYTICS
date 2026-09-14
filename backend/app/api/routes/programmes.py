from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, raise_authz
from app.db.session import get_db
from app.domain.enums import ActionPermission
from app.models import Programme, User
from app.schemas.api import ProgrammeSummary
from app.services.authorization import AuthorizationError, can_access_programme, require_action

router = APIRouter(prefix="/programmes", tags=["programmes"])


@router.get("", response_model=list[ProgrammeSummary])
def list_programmes(
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ProgrammeSummary]:
    try:
        require_action(session, user, ActionPermission.VIEW)
    except AuthorizationError as error:
        raise_authz(error)
    rows = session.scalars(
        select(Programme).where(Programme.active.is_(True), Programme.first_release.is_(True))
    ).all()
    return [
        ProgrammeSummary(code=row.code, name=row.name, sensitive=row.sensitive)
        for row in rows
        if can_access_programme(session, user, row.code)
    ]

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, raise_authz
from app.db.session import get_db
from app.models import Role, User, UserRole
from app.schemas.api import CurrentContextResponse, OrgUnitSummary
from app.services.authorization import (
    AuthorizationError,
    geography_scope_units,
    primary_landing_org_unit,
    programme_scope_codes,
    resolve_landing_org_units,
    user_actions,
)

router = APIRouter(tags=["me"])


def _org_summary(unit) -> OrgUnitSummary:
    return OrgUnitSummary(
        id=unit.id,
        code=unit.code,
        name=unit.name,
        level_type=unit.level_type,
        parent_id=unit.parent_id,
        path=unit.path,
    )


@router.get("/me/context", response_model=CurrentContextResponse)
def me_context(
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CurrentContextResponse:
    try:
        landing = primary_landing_org_unit(session, user)
        roots = resolve_landing_org_units(session, user)
        scopes = geography_scope_units(session, user)
        actions = sorted(user_actions(session, user))
        programmes = sorted(programme_scope_codes(session, user))
        role_codes = list(
            session.scalars(
                select(Role.code)
                .join(UserRole, UserRole.role_id == Role.id)
                .where(UserRole.user_id == user.id, Role.is_active.is_(True))
            ).all()
        )
    except AuthorizationError as error:
        raise_authz(error)
    return CurrentContextResponse(
        user_id=user.id,
        username=user.username,
        display_name=user.display_name,
        role_codes=role_codes,
        landing_org_unit=_org_summary(landing) if landing else None,
        landing_org_units=[_org_summary(unit) for unit in roots],
        geography_scopes=[_org_summary(unit) for unit in scopes],
        programmes=programmes,
        actions=actions,
        identity_provider=user.identity_provider,
    )

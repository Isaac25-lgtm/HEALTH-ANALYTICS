from datetime import date

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, parse_uuid, raise_authz
from app.db.session import get_db
from app.domain.enums import ActionPermission
from app.models import User
from app.schemas.api import OrgUnitSummary
from app.services.authorization import (
    AuthorizationError,
    can_access_org_unit,
    child_org_units,
    require_action,
    require_org_unit_access,
)
from app.services.geography import ancestors as geography_ancestors
from app.services.geometry import map_feature_collection

router = APIRouter(prefix="/org-units", tags=["org-units"])


def _summary(unit) -> OrgUnitSummary:
    return OrgUnitSummary(
        id=unit.id,
        code=unit.code,
        name=unit.name,
        level_type=unit.level_type,
        parent_id=unit.parent_id,
        path=unit.path,
    )


@router.get("/{org_unit_id}", response_model=OrgUnitSummary)
def get_org_unit(
    org_unit_id: str,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> OrgUnitSummary:
    try:
        require_action(session, user, ActionPermission.VIEW)
        unit = require_org_unit_access(session, user, parse_uuid(org_unit_id, "org_unit_id"))
    except AuthorizationError as error:
        raise_authz(error)
    return _summary(unit)


@router.get("/{org_unit_id}/children", response_model=list[OrgUnitSummary])
def list_children(
    org_unit_id: str,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[OrgUnitSummary]:
    try:
        require_action(session, user, ActionPermission.VIEW)
        parent = require_org_unit_access(session, user, parse_uuid(org_unit_id, "org_unit_id"))
        children = [
            child
            for child in child_org_units(session, parent)
            if can_access_org_unit(session, user, child)
        ]
    except AuthorizationError as error:
        raise_authz(error)
    return [_summary(child) for child in children]


@router.get("/{org_unit_id}/ancestors", response_model=list[OrgUnitSummary])
def list_ancestors(
    org_unit_id: str,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[OrgUnitSummary]:
    try:
        require_action(session, user, ActionPermission.VIEW)
        unit = require_org_unit_access(session, user, parse_uuid(org_unit_id, "org_unit_id"))
        chain = [
            ancestor
            for ancestor in geography_ancestors(session, unit)
            if can_access_org_unit(session, user, ancestor)
        ]
    except AuthorizationError as error:
        raise_authz(error)
    return [_summary(item) for item in chain]


@router.get("/{org_unit_id}/map-geometry")
def get_map_geometry(
    org_unit_id: str,
    as_of: date | None = None,
    simplify: bool = False,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> JSONResponse:
    """Return the nearest mapped child level for the selected authorised unit."""
    try:
        require_action(session, user, ActionPermission.VIEW)
        unit = require_org_unit_access(session, user, parse_uuid(org_unit_id, "org_unit_id"))
    except AuthorizationError as error:
        raise_authz(error)
    payload = map_feature_collection(session, user, unit, as_of=as_of, simplify=simplify)
    return JSONResponse(
        content=payload,
        headers={"Cache-Control": "private, max-age=3600", "Vary": "Cookie"},
    )

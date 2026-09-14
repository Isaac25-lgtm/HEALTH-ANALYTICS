from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, raise_authz
from app.db.session import get_db
from app.domain.enums import ActionPermission
from app.models import EventFieldMapping, SourceMapping, User
from app.schemas.api import MappingResponse
from app.services.authorization import AuthorizationError, require_action

router = APIRouter(prefix="/mappings", tags=["mappings"])


@router.get("", response_model=list[MappingResponse])
def list_mappings(
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[MappingResponse]:
    try:
        require_action(session, user, ActionPermission.MANAGE_MAPPINGS)
    except AuthorizationError as error:
        raise_authz(error)
    rows = session.scalars(select(SourceMapping)).all()
    return [
        MappingResponse(
            id=row.id,
            internal_source_key=row.internal_source_key,
            mapping_version=row.mapping_version,
            enabled=row.enabled,
            item_kind=row.item_kind,
            dhis2_item_uid=row.dhis2_item_uid,
            notes=row.notes,
        )
        for row in rows
    ]


@router.get("/events")
def list_event_mappings(
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    try:
        require_action(session, user, ActionPermission.MANAGE_MAPPINGS)
    except AuthorizationError as error:
        raise_authz(error)
    rows = session.scalars(select(EventFieldMapping)).all()
    return [
        {
            "id": str(row.id),
            "internal_semantic_field": row.internal_semantic_field,
            "event_type": row.event_type,
            "mapping_version": row.mapping_version,
            "enabled": row.enabled,
            "source_data_element_uid": row.source_data_element_uid,
            "notes": row.notes,
        }
        for row in rows
    ]

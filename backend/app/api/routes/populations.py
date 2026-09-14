from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, parse_uuid, raise_authz
from app.db.session import get_db
from app.domain.enums import ActionPermission, ApprovalStatus
from app.models import PopulationValue, PopulationVersion, User
from app.schemas.api import (
    FacilityPopulationDecisionRequest,
    FacilityPopulationRequest,
    PopulationResolveResponse,
    PopulationVersionImportRequest,
    PopulationVersionResponse,
)
from app.services.audit import write_audit
from app.services.authorization import AuthorizationError, require_action, require_org_unit_access
from app.services.population import (
    approve_facility_population,
    approve_population_version,
    enter_facility_population,
    import_population_version,
    period_fraction,
    reject_facility_population,
    reject_population_version,
    resolve_population,
)

router = APIRouter(prefix="/populations", tags=["populations"])


@router.get("")
def list_populations(
    org_unit_id: str,
    year: int | None = None,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    try:
        require_action(session, user, ActionPermission.VIEW)
        unit = require_org_unit_access(session, user, parse_uuid(org_unit_id, "org_unit_id"))
    except AuthorizationError as error:
        raise_authz(error)
    query = (
        select(PopulationValue)
        .join(PopulationVersion, PopulationVersion.id == PopulationValue.version_id)
        .where(
            PopulationValue.org_unit_id == unit.id,
            PopulationVersion.approval_status == ApprovalStatus.APPROVED.value,
        )
    )
    if year is not None:
        query = query.where(PopulationValue.year == year)
    rows = session.scalars(query).all()
    return [
        {
            "org_unit_id": str(row.org_unit_id),
            "year": row.year,
            "population": float(row.population),
            "version_id": str(row.version_id),
        }
        for row in rows
    ]


def _version_response(session: Session, version: PopulationVersion) -> PopulationVersionResponse:
    row_count = session.scalar(
        select(func.count(PopulationValue.id)).where(PopulationValue.version_id == version.id)
    )
    return PopulationVersionResponse(
        id=version.id,
        code=version.code,
        name=version.name,
        source_name=version.source_name,
        population_type=version.population_type,
        approval_status=version.approval_status,
        row_count=int(row_count or 0),
    )


@router.get("/versions", response_model=list[PopulationVersionResponse])
def list_population_versions(
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[PopulationVersionResponse]:
    try:
        require_action(session, user, ActionPermission.VIEW)
    except AuthorizationError as error:
        raise_authz(error)
    versions = session.scalars(
        select(PopulationVersion).order_by(PopulationVersion.created_at.desc(), PopulationVersion.code)
    ).all()
    return [_version_response(session, version) for version in versions]


@router.post("/import", response_model=PopulationVersionResponse, status_code=201)
def import_population(
    body: PopulationVersionImportRequest,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PopulationVersionResponse:
    try:
        version = import_population_version(
            session,
            user,
            code=body.code,
            name=body.name,
            source_name=body.source_name,
            source_document=body.source_document,
            population_type=body.population_type.value,
            valid_from=body.valid_from,
            valid_to=body.valid_to,
            notes=body.notes,
            rows=[row.model_dump() for row in body.rows],
        )
    except AuthorizationError as error:
        session.rollback()
        raise_authz(error)
    session.commit()
    return _version_response(session, version)


@router.post("/versions/{version_id}/approve", response_model=PopulationVersionResponse)
def approve_version(
    version_id: str,
    body: FacilityPopulationDecisionRequest | None = None,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PopulationVersionResponse:
    try:
        version = approve_population_version(
            session,
            user,
            parse_uuid(version_id, "version_id"),
            reason=body.reason if body else None,
        )
    except AuthorizationError as error:
        session.rollback()
        raise_authz(error)
    session.commit()
    return _version_response(session, version)


@router.post("/versions/{version_id}/reject", response_model=PopulationVersionResponse)
def reject_version(
    version_id: str,
    body: FacilityPopulationDecisionRequest | None = None,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PopulationVersionResponse:
    try:
        version = reject_population_version(
            session,
            user,
            parse_uuid(version_id, "version_id"),
            reason=body.reason if body else None,
        )
    except AuthorizationError as error:
        session.rollback()
        raise_authz(error)
    session.commit()
    return _version_response(session, version)


@router.get("/resolve", response_model=PopulationResolveResponse)
def resolve(
    org_unit_id: str,
    period: str,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PopulationResolveResponse:
    try:
        require_action(session, user, ActionPermission.VIEW)
        unit = require_org_unit_access(session, user, parse_uuid(org_unit_id, "org_unit_id"))
    except AuthorizationError as error:
        raise_authz(error)
    result = resolve_population(session, unit, period_key=period)
    return PopulationResolveResponse(
        status=result.status,
        population=result.population,
        year=result.year,
        version_id=result.version_id,
        version_code=result.version_code,
        source=result.source,
        policy=result.policy,
        reason=result.reason,
        period_fraction=period_fraction(period),
        selection_reason=result.selection_reason,
        facility_population_entry_id=result.used_facility_entry_id,
        approval_status=result.approval_status,
        population_type=result.population_type,
    )


@router.post("/facility")
def create_facility_population(
    body: FacilityPopulationRequest,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    try:
        entry = enter_facility_population(
            session,
            user,
            org_unit_id=body.org_unit_id,
            year=body.year,
            population=body.population,
            source_name=body.source_name,
            population_type=body.population_type.value,
            reason=body.reason,
            notes=body.notes,
        )
    except AuthorizationError as error:
        raise_authz(error)
    write_audit(
        session,
        actor_user_id=user.id,
        action="facility_population_entered",
        resource_type="facility_population_entry",
        resource_id=str(entry.id),
        after={"year": body.year, "org_unit_id": str(body.org_unit_id)},
        commit=True,
    )
    return {"id": str(entry.id), "status": entry.approval_status, "year": entry.year}


@router.post("/facility/{entry_id}/approve")
def approve_facility(
    entry_id: str,
    body: FacilityPopulationDecisionRequest | None = None,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    try:
        entry = approve_facility_population(
            session,
            user,
            parse_uuid(entry_id, "entry_id"),
            reason=body.reason if body else None,
        )
    except AuthorizationError as error:
        raise_authz(error)
    session.commit()
    return {
        "id": str(entry.id),
        "status": entry.approval_status,
        "is_current_approved": entry.is_current_approved,
        "year": entry.year,
    }


@router.post("/facility/{entry_id}/reject")
def reject_facility(
    entry_id: str,
    body: FacilityPopulationDecisionRequest | None = None,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    try:
        entry = reject_facility_population(
            session,
            user,
            parse_uuid(entry_id, "entry_id"),
            reason=body.reason if body else None,
        )
    except AuthorizationError as error:
        raise_authz(error)
    session.commit()
    return {"id": str(entry.id), "status": entry.approval_status, "year": entry.year}

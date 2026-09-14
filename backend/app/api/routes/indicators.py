from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, parse_uuid, raise_authz
from app.db.session import get_db
from app.domain.enums import ActionPermission
from app.models import Indicator, IndicatorVersion, Programme, User
from app.schemas.api import IndicatorSummary, IndicatorVersionSummary
from app.services.authorization import AuthorizationError, can_access_programme, require_action

router = APIRouter(prefix="/indicators", tags=["indicators"])


@router.get("", response_model=list[IndicatorSummary])
def list_indicators(
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[IndicatorSummary]:
    try:
        require_action(session, user, ActionPermission.VIEW)
    except AuthorizationError as error:
        raise_authz(error)
    rows = session.scalars(select(Indicator).where(Indicator.active.is_(True))).all()
    out: list[IndicatorSummary] = []
    for row in rows:
        programme = session.get(Programme, row.programme_id)
        if programme is None or not can_access_programme(session, user, programme.code):
            continue
        current = session.scalar(
            select(IndicatorVersion).where(
                IndicatorVersion.indicator_id == row.id,
                IndicatorVersion.is_current.is_(True),
            )
        )
        out.append(
            IndicatorSummary(
                id=row.id,
                code=row.code,
                name=row.name,
                programme=programme.code,
                current_version=current.formula_version if current else None,
            )
        )
    return out


@router.get("/{indicator_id}/versions", response_model=list[IndicatorVersionSummary])
def list_versions(
    indicator_id: str,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[IndicatorVersionSummary]:
    try:
        require_action(session, user, ActionPermission.VIEW)
        indicator = session.get(Indicator, parse_uuid(indicator_id, "indicator_id"))
        if indicator is None:
            raise AuthorizationError("not_found", "Indicator not found.")
        programme = session.get(Programme, indicator.programme_id)
        if programme is None or not can_access_programme(session, user, programme.code):
            raise AuthorizationError("forbidden_programme", "Indicator is outside programme scope.")
    except AuthorizationError as error:
        raise_authz(error)
    versions = session.scalars(
        select(IndicatorVersion).where(IndicatorVersion.indicator_id == indicator.id)
    ).all()
    return [
        IndicatorVersionSummary(
            id=row.id,
            formula_version=row.formula_version,
            unit=row.unit,
            multiplier=row.multiplier,
            denominator_type=row.denominator_type,
            period_adjustment=row.period_adjustment,
            is_current=row.is_current,
            methodology_text=row.methodology_text,
        )
        for row in versions
    ]

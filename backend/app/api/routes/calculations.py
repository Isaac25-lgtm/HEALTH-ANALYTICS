from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, parse_uuid, raise_authz, require_write
from app.db.session import get_db
from app.domain.enums import ActionPermission
from app.domain.periods import PeriodError, parse_period
from app.models import (
    CalculatedValue,
    CalculationRun,
    FacilityPopulationEntry,
    Indicator,
    IndicatorVersion,
    Programme,
    User,
)
from app.schemas.api import CalculationRunRequest, CalculationRunResponse, CalculationValueResponse
from app.services.authorization import (
    AuthorizationError,
    can_access_programme,
    require_action,
    require_org_unit_access,
    require_programme_access,
)
from app.services.calculation import run_calculation
from app.services.quality import scan_quality

router = APIRouter(prefix="/calculations", tags=["calculations"])


def _serialize(session: Session, run: CalculationRun, user: User) -> CalculationRunResponse:
    rows = session.scalars(select(CalculatedValue).where(CalculatedValue.calculation_run_id == run.id)).all()
    values = []
    for row in rows:
        version = session.get(IndicatorVersion, row.indicator_version_id)
        indicator = session.get(Indicator, version.indicator_id) if version else None
        if indicator is None:
            continue
        programme = session.get(Programme, indicator.programme_id)
        if programme is None or not can_access_programme(session, user, programme.code):
            continue
        facility_entry = (
            session.get(FacilityPopulationEntry, row.facility_population_entry_id)
            if row.facility_population_entry_id
            else None
        )
        values.append(
            CalculationValueResponse(
                indicator_code=indicator.code,
                formula_version=version.formula_version if version else "",
                numerator=float(row.numerator) if row.numerator is not None else None,
                denominator=float(row.denominator) if row.denominator is not None else None,
                raw_value=float(row.raw_value) if row.raw_value is not None else None,
                display_value=row.display_value,
                unit=row.unit,
                status=row.status,
                performance_status=row.performance_status,
                quality_status=row.quality_status,
                population_year=row.population_year,
                calculation_run_id=run.id,
                blue_reason=row.blue_reason,
                population_version_id=row.population_version_id,
                facility_population_entry_id=row.facility_population_entry_id,
                population_source=facility_entry.source_name if facility_entry else None,
                population_approval_status=facility_entry.approval_status if facility_entry else None,
                population_type=facility_entry.population_type if facility_entry else None,
                aggregation_policy=row.aggregation_policy,
                mapping_version=row.mapping_version,
            )
        )
    return CalculationRunResponse(
        id=run.id,
        status=run.status,
        period=run.period,
        org_unit_id=run.geography_org_unit_id,
        quality_flag_count=run.quality_flag_count,
        config_snapshot=run.config_snapshot,
        values=values,
    )


def _validate_indicator_codes(session: Session, programme: Programme, codes: list[str] | None) -> None:
    if not codes:
        return
    rows = session.scalars(select(Indicator).where(Indicator.code.in_(codes))).all()
    found = {row.code: row for row in rows}
    unknown = [code for code in codes if code not in found]
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "unknown_indicator", "message": "One or more indicator codes are unknown."},
        )
    for code in codes:
        row = found[code]
        if row.programme_id != programme.id:
            raise AuthorizationError(
                "forbidden_programme",
                f"Indicator {code} is outside the authorised programme set.",
            )


@router.post("/run", response_model=CalculationRunResponse)
def create_run(
    body: CalculationRunRequest,
    session: Session = Depends(require_write),
    user: User = Depends(get_current_user),
) -> CalculationRunResponse:
    try:
        parse_period(body.period)
        require_action(session, user, ActionPermission.VIEW)
        unit = require_org_unit_access(session, user, body.org_unit_id)
        programme_code = body.programme.value
        require_programme_access(session, user, programme_code)
        programme = session.scalar(select(Programme).where(Programme.code == programme_code))
        if programme is None:
            raise AuthorizationError("forbidden_programme", "Programme is not recognised.")
        _validate_indicator_codes(session, programme, body.indicator_codes)
    except PeriodError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_period", "message": str(exc)},
        ) from exc
    except AuthorizationError as error:
        raise_authz(error)
    run = run_calculation(
        session,
        org_unit=unit,
        period=body.period,
        user=user,
        programme_codes=[programme_code],
        indicator_codes=body.indicator_codes,
    )
    scan_quality(session, org_unit=unit, period=body.period, calculation_run=run)
    session.commit()
    return _serialize(session, run, user)


@router.get("/{run_id}", response_model=CalculationRunResponse)
def get_run(
    run_id: str,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CalculationRunResponse:
    try:
        require_action(session, user, ActionPermission.VIEW)
        run = session.get(CalculationRun, parse_uuid(run_id, "run_id"))
        if run is None:
            raise AuthorizationError("not_found", "Calculation run not found.")
        if run.geography_org_unit_id:
            require_org_unit_access(session, user, run.geography_org_unit_id)
        if run.programme_id:
            programme = session.get(Programme, run.programme_id)
            if programme is None or not can_access_programme(session, user, programme.code):
                raise AuthorizationError(
                    "forbidden_programme",
                    "Calculation run is outside the authorised programme scope.",
                )
    except AuthorizationError as error:
        raise_authz(error)
    return _serialize(session, run, user)

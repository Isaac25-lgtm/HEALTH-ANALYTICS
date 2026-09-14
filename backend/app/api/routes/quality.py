from datetime import UTC, datetime

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy import false, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, parse_uuid, raise_authz, require_write
from app.db.session import get_db
from app.domain.enums import ActionPermission, QualityStatus
from app.domain.quality_privacy import contains_sensitive_identifier, redact_evidence
from app.models import DataQualityFlag, Programme, User
from app.schemas.api import OrdinaryQualityFlagResponse, SensitiveQualityFlagResponse
from app.services.audit import write_audit
from app.services.authorization import (
    AuthorizationError,
    authorised_org_unit_ids,
    authorised_programme_ids,
    can_access_programme,
    has_action,
    require_action,
    require_programme_access,
)

router = APIRouter(prefix="/quality", tags=["quality"])

EVENT_RULES = {
    "ACTIVE_MPDSR_WORKFLOW",
    "NOTIFICATION_BEFORE_DEATH",
    "REVIEW_BEFORE_DEATH",
    "REVIEW_INTERVAL_OUT_OF_RANGE",
    "MISSING_CAUSE",
    "MISSING_CRITICAL_DATE",
    "POSSIBLE_DUPLICATE_EVENT",
}


def _is_sensitive(row: DataQualityFlag) -> bool:
    return bool(row.event_uid) or row.rule_id in EVENT_RULES or contains_sensitive_identifier(row.evidence)


def _can_read_sensitive(session: Session, user: User, row: DataQualityFlag) -> bool:
    if not has_action(session, user, ActionPermission.VIEW_MPDSR_EVENTS):
        return False
    if row.programme_id:
        programme = session.get(Programme, row.programme_id)
        return bool(programme and can_access_programme(session, user, programme.code))
    return can_access_programme(session, user, "MPDSR")


def _to_ordinary(row: DataQualityFlag) -> OrdinaryQualityFlagResponse:
    return OrdinaryQualityFlagResponse(
        id=row.id,
        rule_id=row.rule_id,
        category=row.category,
        severity=row.severity,
        status=row.status,
        explanation=row.explanation,
        period=row.period,
        org_unit_id=row.org_unit_id,
        programme_id=row.programme_id,
        evidence=redact_evidence(row.evidence),
    )


def _to_sensitive(row: DataQualityFlag) -> SensitiveQualityFlagResponse:
    return SensitiveQualityFlagResponse(
        id=row.id,
        rule_id=row.rule_id,
        category=row.category,
        severity=row.severity,
        status=row.status,
        explanation=row.explanation,
        period=row.period,
        org_unit_id=row.org_unit_id,
        programme_id=row.programme_id,
        evidence=row.evidence,
        event_uid=row.event_uid,
    )


@router.get("/flags")
def list_flags(
    org_unit_id: str | None = None,
    period: str | None = None,
    programme_id: str | None = None,
    indicator_id: str | None = None,
    unresolved_only: bool = Query(default=True),
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[OrdinaryQualityFlagResponse] | list[SensitiveQualityFlagResponse]:
    try:
        require_action(session, user, ActionPermission.VIEW)
        geo_ids = authorised_org_unit_ids(session, user)
        prog_ids = authorised_programme_ids(session, user)
        if org_unit_id:
            parsed_org = parse_uuid(org_unit_id, "org_unit_id")
            if parsed_org not in geo_ids:
                raise AuthorizationError("forbidden_geography", "Organisation unit is outside authorised geography.")
        if programme_id:
            parsed_prog = parse_uuid(programme_id, "programme_id")
            programme = session.get(Programme, parsed_prog)
            if programme is None:
                raise AuthorizationError("not_found", "Programme not found.")
            require_programme_access(session, user, programme.code)
    except AuthorizationError as error:
        raise_authz(error)
    query = select(DataQualityFlag).where(DataQualityFlag.org_unit_id.in_(geo_ids))
    if prog_ids:
        query = query.where(
            (DataQualityFlag.programme_id.in_(prog_ids)) | (DataQualityFlag.programme_id.is_(None))
        )
    elif not user.is_system_admin:
        query = query.where(false())
    if org_unit_id:
        query = query.where(DataQualityFlag.org_unit_id == parse_uuid(org_unit_id, "org_unit_id"))
    if period:
        query = query.where(DataQualityFlag.period == period)
    if programme_id:
        query = query.where(DataQualityFlag.programme_id == parse_uuid(programme_id, "programme_id"))
    if indicator_id:
        query = query.where(DataQualityFlag.indicator_id == parse_uuid(indicator_id, "indicator_id"))
    if unresolved_only:
        query = query.where(DataQualityFlag.status.in_(["open", "acknowledged"]))
    ordinary: list[OrdinaryQualityFlagResponse] = []
    sensitive: list[SensitiveQualityFlagResponse] = []
    include_sensitive = False
    for row in session.scalars(query).all():
        if _is_sensitive(row):
            if _can_read_sensitive(session, user, row):
                include_sensitive = True
                sensitive.append(_to_sensitive(row))
            else:
                ordinary.append(_to_ordinary(row))
        else:
            ordinary.append(_to_ordinary(row))
    if include_sensitive:
        return sensitive + [
            SensitiveQualityFlagResponse(**item.model_dump(), event_uid=None) for item in ordinary
        ]
    return ordinary


@router.get("/flags/{flag_id}")
def get_flag(
    flag_id: str,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        require_action(session, user, ActionPermission.VIEW)
        row = session.get(DataQualityFlag, parse_uuid(flag_id, "flag_id"))
        if row is None:
            raise AuthorizationError("not_found", "Quality flag not found.")
        geo_ids = authorised_org_unit_ids(session, user)
        prog_ids = authorised_programme_ids(session, user)
        if not user.is_system_admin and (
            not geo_ids or (row.org_unit_id is not None and row.org_unit_id not in geo_ids)
        ):
            raise AuthorizationError("forbidden_geography", "Quality flag is outside authorised geography.")
        if not user.is_system_admin and (
            not prog_ids or (row.programme_id is not None and row.programme_id not in prog_ids)
        ):
            raise AuthorizationError("forbidden_programme", "Quality flag is outside authorised programme scope.")
        if _is_sensitive(row):
            if not _can_read_sensitive(session, user, row):
                raise AuthorizationError(
                    "forbidden_action",
                    "MPDSR event-derived quality evidence requires the MPDSR programme and view_mpdsr_events.",
                )
            return _to_sensitive(row)
    except AuthorizationError as error:
        raise_authz(error)
    return _to_ordinary(row)


def _load_flag_for_mutation(session: Session, user: User, flag_id: str) -> DataQualityFlag:
    require_action(session, user, ActionPermission.MANAGE_QUALITY)
    row = session.get(DataQualityFlag, parse_uuid(flag_id, "flag_id"))
    if row is None:
        raise AuthorizationError("not_found", "Quality flag not found.")
    geo_ids = authorised_org_unit_ids(session, user)
    prog_ids = authorised_programme_ids(session, user)
    if not user.is_system_admin and (
        not geo_ids or (row.org_unit_id is not None and row.org_unit_id not in geo_ids)
    ):
        raise AuthorizationError("forbidden_geography", "Quality flag is outside authorised geography.")
    if not user.is_system_admin and (
        not prog_ids or (row.programme_id is not None and row.programme_id not in prog_ids)
    ):
        raise AuthorizationError("forbidden_programme", "Quality flag is outside authorised programme scope.")
    return row


def _mutate_flag(
    session: Session,
    user: User,
    flag_id: str,
    *,
    target: str,
    allowed_from: set[str],
    reason: str | None,
    require_reason: bool,
):
    try:
        row = _load_flag_for_mutation(session, user, flag_id)
        if require_reason and not (reason or "").strip():
            raise AuthorizationError("invalid_input", "A reason is required for this quality action.")
        if row.status not in allowed_from:
            raise AuthorizationError("invalid_input", f"Quality flag status {row.status} cannot move to {target}.")
        before = {"status": row.status, "resolution_note": row.resolution_note}
        row.status = target
        if target == QualityStatus.ACKNOWLEDGED.value:
            row.acknowledged_by_user_id = user.id
            row.acknowledged_at = datetime.now(UTC)
        if target == QualityStatus.RESOLVED.value:
            row.resolved_by_user_id = user.id
            row.resolved_at = datetime.now(UTC)
            row.resolution_note = reason
        if target == QualityStatus.SUPPRESSED.value:
            row.resolved_by_user_id = user.id
            row.resolved_at = datetime.now(UTC)
            row.resolution_note = reason
        if target == QualityStatus.OPEN.value:
            row.reopen_count = (row.reopen_count or 0) + 1
            row.resolved_at = None
            row.resolution_note = reason
        write_audit(
            session,
            actor_user_id=user.id,
            action=f"quality_{target}",
            resource_type="data_quality_flag",
            resource_id=str(row.id),
            before=before,
            after={"status": row.status, "resolution_note": row.resolution_note},
            reason=reason,
            commit=False,
        )
    except AuthorizationError as error:
        raise_authz(error)
    return _to_ordinary(row)


@router.post("/flags/{flag_id}/acknowledge")
def acknowledge_flag(
    flag_id: str,
    session: Session = Depends(require_write),
    user: User = Depends(get_current_user),
):
    return _mutate_flag(
        session,
        user,
        flag_id,
        target=QualityStatus.ACKNOWLEDGED.value,
        allowed_from={QualityStatus.OPEN.value},
        reason=None,
        require_reason=False,
    )


@router.post("/flags/{flag_id}/resolve")
def resolve_flag(
    flag_id: str,
    body: dict = Body(default_factory=dict),
    session: Session = Depends(require_write),
    user: User = Depends(get_current_user),
):
    return _mutate_flag(
        session,
        user,
        flag_id,
        target=QualityStatus.RESOLVED.value,
        allowed_from={QualityStatus.OPEN.value, QualityStatus.ACKNOWLEDGED.value},
        reason=body.get("reason"),
        require_reason=True,
    )


@router.post("/flags/{flag_id}/reopen")
def reopen_flag(
    flag_id: str,
    body: dict = Body(default_factory=dict),
    session: Session = Depends(require_write),
    user: User = Depends(get_current_user),
):
    return _mutate_flag(
        session,
        user,
        flag_id,
        target=QualityStatus.OPEN.value,
        allowed_from={QualityStatus.RESOLVED.value, QualityStatus.SUPPRESSED.value},
        reason=body.get("reason"),
        require_reason=True,
    )


@router.post("/flags/{flag_id}/suppress")
def suppress_flag(
    flag_id: str,
    body: dict = Body(default_factory=dict),
    session: Session = Depends(require_write),
    user: User = Depends(get_current_user),
):
    return _mutate_flag(
        session,
        user,
        flag_id,
        target=QualityStatus.SUPPRESSED.value,
        allowed_from={QualityStatus.OPEN.value, QualityStatus.ACKNOWLEDGED.value},
        reason=body.get("reason"),
        require_reason=True,
    )

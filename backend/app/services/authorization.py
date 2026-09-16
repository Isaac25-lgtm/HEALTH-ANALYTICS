from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import ActionPermission, OrgUnitLevel
from app.models import (
    OrgUnit,
    Role,
    RolePermission,
    User,
    UserGeographyScope,
    UserPermission,
    UserProgrammeScope,
    UserRole,
)


class AuthorizationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def _grant_current(valid_from: date | None, valid_to: date | None, today: date | None = None) -> bool:
    as_of = today or date.today()
    if valid_from and as_of < valid_from:
        return False
    if valid_to and as_of > valid_to:
        return False
    return True


def user_actions(session: Session, user: User) -> set[str]:
    if user.is_system_admin:
        return {item.value for item in ActionPermission}
    role_ids = session.scalars(
        select(UserRole.role_id)
        .join(Role, Role.id == UserRole.role_id)
        .where(UserRole.user_id == user.id, Role.is_active.is_(True))
    ).all()
    actions = set(
        session.scalars(
            select(RolePermission.action).where(RolePermission.role_id.in_(role_ids))
        ).all()
    )
    extras = session.scalars(
        select(UserPermission.action).where(UserPermission.user_id == user.id)
    ).all()
    actions.update(extras)
    return actions


def has_action(session: Session, user: User, action: ActionPermission | str) -> bool:
    wanted = action.value if isinstance(action, ActionPermission) else action
    return wanted in user_actions(session, user)


def require_action(session: Session, user: User, action: ActionPermission) -> None:
    if not has_action(session, user, action):
        raise AuthorizationError("forbidden_action", f"Missing action permission: {action.value}")


def geography_scope_units(session: Session, user: User) -> list[OrgUnit]:
    rows = session.scalars(
        select(UserGeographyScope).where(
            UserGeographyScope.user_id == user.id,
            UserGeographyScope.is_active.is_(True),
        )
    ).all()
    ids = [row.org_unit_id for row in rows if _grant_current(row.valid_from, row.valid_to)]
    if not ids:
        return []
    return list(session.scalars(select(OrgUnit).where(OrgUnit.id.in_(ids))).all())


def programme_scope_codes(session: Session, user: User) -> set[str]:
    from app.models import Programme

    rows = session.execute(
        select(Programme.code, UserProgrammeScope.is_active, UserProgrammeScope.valid_from, UserProgrammeScope.valid_to)
        .join(UserProgrammeScope, UserProgrammeScope.programme_id == Programme.id)
        .where(UserProgrammeScope.user_id == user.id)
    ).all()
    codes: set[str] = set()
    for code, active, valid_from, valid_to in rows:
        if active and _grant_current(valid_from, valid_to):
            codes.add(code)
    return codes


def is_descendant_or_self(candidate: OrgUnit, ancestor: OrgUnit) -> bool:
    if candidate.id == ancestor.id:
        return True
    prefix = ancestor.path.rstrip("/") + "/"
    return candidate.path == ancestor.path or candidate.path.startswith(prefix)


def authorised_org_unit_ids(session: Session, user: User) -> set[UUID]:
    scopes = geography_scope_units(session, user)
    if user.is_system_admin:
        return {unit.id for unit in session.scalars(select(OrgUnit).where(OrgUnit.active.is_(True))).all()}
    if not scopes:
        return set()
    authorised: set[UUID] = set()
    all_units = session.scalars(select(OrgUnit).where(OrgUnit.active.is_(True))).all()
    for unit in all_units:
        if any(is_descendant_or_self(unit, scope) for scope in scopes):
            authorised.add(unit.id)
    return authorised


def can_access_org_unit(session: Session, user: User, org_unit: OrgUnit) -> bool:
    if user.is_system_admin:
        return True
    scopes = geography_scope_units(session, user)
    return any(is_descendant_or_self(org_unit, scope) for scope in scopes)


def require_org_unit_access(session: Session, user: User, org_unit_id: UUID) -> OrgUnit:
    org_unit = session.get(OrgUnit, org_unit_id)
    if org_unit is None or not org_unit.active:
        raise AuthorizationError("not_found", "Organisation unit not found.")
    if not can_access_org_unit(session, user, org_unit):
        raise AuthorizationError(
            "forbidden_geography",
            "Requested organisation unit is outside the authorised geography.",
        )
    return org_unit


def can_access_programme(session: Session, user: User, programme_code: str) -> bool:
    if user.is_system_admin:
        return True
    return programme_code in programme_scope_codes(session, user)


def require_programme_access(session: Session, user: User, programme_code: str) -> None:
    if not can_access_programme(session, user, programme_code):
        raise AuthorizationError(
            "forbidden_programme",
            f"Programme {programme_code} is outside the authorised programme scope.",
        )


def authorised_programme_ids(session: Session, user: User) -> set[UUID]:
    from app.models import Programme

    codes = programme_scope_codes(session, user)
    if user.is_system_admin:
        return {row.id for row in session.scalars(select(Programme)).all()}
    rows = session.scalars(select(Programme).where(Programme.code.in_(codes))).all()
    return {row.id for row in rows}


def resolve_landing_org_units(session: Session, user: User) -> list[OrgUnit]:
    if user.is_system_admin:
        country = session.scalar(
            select(OrgUnit).where(
                OrgUnit.code == "UG",
                OrgUnit.level_type == OrgUnitLevel.COUNTRY.value,
                OrgUnit.active.is_(True),
                OrgUnit.parent_id.is_(None),
            )
        )
        if country is not None:
            return [country]
    scopes = [unit for unit in geography_scope_units(session, user) if unit.active]
    roots: list[OrgUnit] = []
    for candidate in scopes:
        contained = False
        for other in scopes:
            if candidate.id == other.id:
                continue
            if is_descendant_or_self(candidate, other) and candidate.id != other.id:
                contained = True
                break
        if not contained:
            roots.append(candidate)
    roots.sort(key=lambda unit: (ORG_UNIT_LEVEL_RANK_SAFE(unit.level_type), unit.name))
    return roots


def ORG_UNIT_LEVEL_RANK_SAFE(level: str) -> int:
    try:
        return {
            OrgUnitLevel.COUNTRY.value: 0,
            OrgUnitLevel.REGION.value: 1,
            OrgUnitLevel.SUB_REGION.value: 1,
            OrgUnitLevel.DISTRICT.value: 2,
            OrgUnitLevel.CITY.value: 2,
            OrgUnitLevel.SUB_COUNTY.value: 3,
            OrgUnitLevel.FACILITY.value: 4,
        }[level]
    except KeyError:
        return 99


def primary_landing_org_unit(session: Session, user: User) -> OrgUnit | None:
    roots = resolve_landing_org_units(session, user)
    if not roots:
        return None
    if len(roots) == 1:
        return roots[0]
    best_rank = min(ORG_UNIT_LEVEL_RANK_SAFE(unit.level_type) for unit in roots)
    highest = [unit for unit in roots if ORG_UNIT_LEVEL_RANK_SAFE(unit.level_type) == best_rank]
    return highest[0]


def child_org_units(session: Session, parent: OrgUnit) -> list[OrgUnit]:
    return list(
        session.scalars(
            select(OrgUnit)
            .where(OrgUnit.parent_id == parent.id, OrgUnit.active.is_(True))
            .order_by(OrgUnit.name)
        ).all()
    )

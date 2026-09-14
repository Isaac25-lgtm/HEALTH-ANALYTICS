from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import AGGREGATION_CLASS_RANK, AggregationClass, OrgUnitLevel, aggregation_class
from app.models import OrgUnit, OrgUnitMapping
from app.services.authorization import AuthorizationError


def _path_prefixes(path: str) -> set[str]:
    parts = [part for part in path.strip("/").split("/") if part]
    return {"/" + "/".join(parts[:index]) for index in range(1, len(parts))}


def top_units_of_class(units: list[OrgUnit], cls: AggregationClass | None) -> list[OrgUnit]:
    """Units of one aggregation class that have no ancestor of the same class in ``units``.

    This is the complete, non-overlapping cohort for that class: summing it cannot
    double count a parent together with a nested unit of the same class.
    """
    members = [unit for unit in units if aggregation_class(unit.level_type) == cls]
    member_paths = {unit.path.rstrip("/") for unit in members}
    return [unit for unit in members if not (_path_prefixes(unit.path) & member_paths)]


def has_overlapping_units(units: list[OrgUnit]) -> bool:
    """True when any unit in ``units`` lies inside another unit in the same list."""
    paths = {unit.path.rstrip("/") for unit in units}
    return any(_path_prefixes(unit.path) & paths for unit in units)


def descendant_classes_below(parent: OrgUnit, units: list[OrgUnit]) -> list[AggregationClass]:
    """Aggregation classes present below ``parent``, nearest first."""
    parent_class = aggregation_class(parent.level_type)
    parent_rank = AGGREGATION_CLASS_RANK.get(parent_class, -1) if parent_class else -1
    classes = {
        cls
        for unit in units
        if (cls := aggregation_class(unit.level_type)) is not None and AGGREGATION_CLASS_RANK[cls] > parent_rank
    }
    return sorted(classes, key=lambda cls: AGGREGATION_CLASS_RANK[cls])


class GeographyError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def build_path(parent: OrgUnit | None, code: str) -> str:
    slug = code.strip("/").upper()
    if parent is None:
        return f"/{slug}"
    return f"{parent.path.rstrip('/')}/{slug}"


def would_create_cycle(session: Session, unit: OrgUnit, new_parent: OrgUnit | None) -> bool:
    if new_parent is None:
        return False
    if new_parent.id == unit.id:
        return True
    current = new_parent
    seen: set[UUID] = {unit.id}
    while current is not None:
        if current.id in seen:
            return True
        seen.add(current.id)
        if current.parent_id is None:
            break
        current = session.get(OrgUnit, current.parent_id)
    return False


def create_org_unit(
    session: Session,
    *,
    code: str,
    name: str,
    level_type: OrgUnitLevel | str,
    parent: OrgUnit | None = None,
    ownership: str | None = None,
    facility_level: str | None = None,
) -> OrgUnit:
    level = level_type.value if isinstance(level_type, OrgUnitLevel) else level_type
    unit = OrgUnit(
        code=code,
        name=name,
        level_type=level,
        parent_id=parent.id if parent else None,
        path=build_path(parent, code),
        active=True,
        ownership=ownership,
        facility_level=facility_level,
    )
    session.add(unit)
    session.flush()
    return unit


def assign_parent(session: Session, unit: OrgUnit, parent: OrgUnit | None) -> OrgUnit:
    if would_create_cycle(session, unit, parent):
        raise GeographyError("cycle_detected", "Organisation-unit parent assignment would create a cycle.")
    unit.parent_id = parent.id if parent else None
    unit.path = build_path(parent, unit.code)
    session.flush()
    _repath_descendants(session, unit)
    return unit


def _repath_descendants(session: Session, parent: OrgUnit) -> None:
    children = session.scalars(select(OrgUnit).where(OrgUnit.parent_id == parent.id)).all()
    for child in children:
        child.path = build_path(parent, child.code)
        _repath_descendants(session, child)


def ancestors(session: Session, unit: OrgUnit, *, include_inactive: bool = False) -> list[OrgUnit]:
    chain: list[OrgUnit] = []
    current = unit
    seen: set[UUID] = set()
    while current.parent_id is not None:
        if current.parent_id in seen:
            raise GeographyError("cycle_detected", "Existing geography path contains a cycle.")
        seen.add(current.parent_id)
        parent = session.get(OrgUnit, current.parent_id)
        if parent is None:
            break
        if parent.active or include_inactive:
            chain.append(parent)
        current = parent
    return chain


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def descendants(
    session: Session,
    unit: OrgUnit,
    *,
    include_self: bool = False,
    active_only: bool = True,
) -> list[OrgUnit]:
    prefix = unit.path.rstrip("/") + "/"
    batch = session.info.get("calc_batch")
    if batch and batch.get("units") is not None:
        rows = [
            item
            for item in batch["units"]
            if item.id != unit.id and item.path.startswith(prefix)
        ]
        if active_only:
            rows = [item for item in rows if item.active]
        rows.sort(key=lambda item: item.path)
        self_unit = batch.get("unit_by_id", {}).get(unit.id, unit)
        if include_self and (self_unit.active or not active_only):
            return [self_unit, *rows]
        return rows
    query = select(OrgUnit).where(OrgUnit.path.like(escape_like(prefix) + "%", escape="\\"))
    if active_only:
        query = query.where(OrgUnit.active.is_(True))
    rows = list(session.scalars(query.order_by(OrgUnit.path)).all())
    if include_self and (unit.active or not active_only):
        return [unit, *rows]
    return rows


def authorised_subtree(session: Session, user, root: OrgUnit) -> list[OrgUnit]:
    from app.services.authorization import can_access_org_unit

    units = descendants(session, root, include_self=True)
    return [unit for unit in units if can_access_org_unit(session, user, unit)]


def validate_bulk_rows(session: Session, rows: list[dict]) -> list[dict]:
    """Validate geography import rows. Does not invent national structure."""
    errors: list[dict] = []
    codes = [str(row.get("code") or "") for row in rows]
    if len(codes) != len(set(codes)):
        errors.append({"code": "duplicate_code", "message": "Import contains duplicate organisation-unit codes."})
    existing = {row.code for row in session.scalars(select(OrgUnit)).all()}
    known_parents = set(existing) | set(codes)
    valid_levels = {item.value for item in OrgUnitLevel}
    for row in rows:
        code = str(row.get("code") or "")
        parent_code = row.get("parent_code")
        level = row.get("level_type")
        if not code:
            errors.append({"code": "missing_code", "message": "Organisation-unit code is required."})
        if level not in valid_levels:
            errors.append({"code": "invalid_level", "message": f"{code} has an invalid level_type."})
        if parent_code and parent_code not in known_parents:
            errors.append({"code": "missing_parent", "message": f"{code} references unknown parent {parent_code}."})
        if parent_code == code:
            errors.append({"code": "cycle_detected", "message": f"{code} cannot be its own parent."})
    return errors


def unmapped_dhis2_org_units(session: Session, incoming_uids: list[str]) -> list[str]:
    mapped = set(
        session.scalars(select(OrgUnitMapping.external_uid).where(OrgUnitMapping.source_system == "dhis2")).all()
    )
    return sorted({uid for uid in incoming_uids if uid and uid not in mapped})


def intervals_overlap(
    left_from: date | None,
    left_to: date | None,
    right_from: date | None,
    right_to: date | None,
) -> bool:
    start_left = left_from or date.min
    end_left = left_to or date.max
    start_right = right_from or date.min
    end_right = right_to or date.max
    return start_left <= end_right and start_right <= end_left


def mapping_in_force(mapping: OrgUnitMapping, as_of: date) -> bool:
    if mapping.valid_from and as_of < mapping.valid_from:
        return False
    if mapping.valid_to and as_of > mapping.valid_to:
        return False
    return True


def resolve_org_unit_by_dhis2_uid(
    session: Session,
    uid: str,
    *,
    as_of: date | None = None,
) -> OrgUnit | None:
    rows = list(
        session.scalars(
            select(OrgUnitMapping).where(
                OrgUnitMapping.source_system == "dhis2",
                OrgUnitMapping.external_uid == uid,
            )
        ).all()
    )
    if not rows:
        return None
    effective = as_of or date.today()
    in_force = [row for row in rows if mapping_in_force(row, effective)]
    if len(in_force) > 1:
        raise AuthorizationError(
            "invalid_input",
            "Overlapping active DHIS2 organisation-unit mappings exist for the requested source UID.",
        )
    if not in_force:
        return None
    return session.get(OrgUnit, in_force[0].org_unit_id)


def reject_overlapping_org_unit_mappings(session: Session, candidate: OrgUnitMapping) -> None:
    query = select(OrgUnitMapping).where(
        OrgUnitMapping.source_system == candidate.source_system,
        OrgUnitMapping.external_uid == candidate.external_uid,
    )
    if candidate.id is not None:
        query = query.where(OrgUnitMapping.id != candidate.id)
    for row in session.scalars(query).all():
        if intervals_overlap(candidate.valid_from, candidate.valid_to, row.valid_from, row.valid_to):
            raise AuthorizationError(
                "invalid_input",
                "Active organisation-unit mappings for the same source UID must not overlap.",
            )


def historical_active(unit: OrgUnit) -> bool:
    return unit.active

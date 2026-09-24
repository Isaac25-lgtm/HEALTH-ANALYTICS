from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta
from json import JSONDecodeError
from pathlib import Path
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, defer

from app.domain.enums import ORG_UNIT_LEVEL_RANK, ActionPermission, OrgUnitLevel, aggregation_class
from app.models import Geometry, OrgUnit, User
from app.services.audit import write_audit
from app.services.authorization import AuthorizationError, can_access_org_unit, require_action
from app.services.geography import ancestors, descendants


class GeometryImportError(ValueError):
    pass


@dataclass(frozen=True)
class GeometryImportRecord:
    org_unit_id: UUID
    org_unit_code: str
    feature_name: str
    geometry: dict


@dataclass
class GeometryImportPlan:
    source_path: Path
    level_type: str
    source_sha256: str
    total_features: int = 0
    records: list[GeometryImportRecord] = field(default_factory=list)
    unmatched: list[dict] = field(default_factory=list)
    ambiguous: list[dict] = field(default_factory=list)
    invalid: list[dict] = field(default_factory=list)
    duplicate_org_unit_codes: list[str] = field(default_factory=list)
    # Owner-approved spelling aliases actually used, as {"feature": ..., "org_unit_code": ...}.
    aliases_applied: list[dict] = field(default_factory=list)

    def summary(self, detail_limit: int = 50) -> dict:
        return {
            "source_file": self.source_path.name,
            "source_sha256": self.source_sha256,
            "level_type": self.level_type,
            "total_features": self.total_features,
            "matched_features": len(self.records),
            "unmatched_count": len(self.unmatched),
            "ambiguous_count": len(self.ambiguous),
            "invalid_count": len(self.invalid),
            "duplicate_org_unit_codes": self.duplicate_org_unit_codes,
            "aliases_applied": self.aliases_applied,
            "unmatched": self.unmatched[:detail_limit],
            "ambiguous": self.ambiguous[:detail_limit],
            "invalid": self.invalid[:detail_limit],
            "details_truncated": any(
                len(items) > detail_limit for items in (self.unmatched, self.ambiguous, self.invalid)
            ),
        }


def _normalise_name(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    return " ".join("".join(char if char.isalnum() else " " for char in text).casefold().split())


def source_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_geojson_features(path: Path):
    """Stream the top-level GeoJSON features array without loading the full source file."""
    decoder = json.JSONDecoder()
    buffer = ""
    found_array = False
    with path.open("r", encoding="utf-8-sig") as handle:
        while not found_array:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                raise GeometryImportError("The file does not contain a GeoJSON features array.")
            buffer += chunk
            key_at = buffer.find('"features"')
            if key_at < 0:
                buffer = buffer[-64:]
                continue
            colon_at = buffer.find(":", key_at + len('"features"'))
            array_at = buffer.find("[", colon_at + 1) if colon_at >= 0 else -1
            if array_at < 0:
                if len(buffer) > 2 * 1024 * 1024:
                    raise GeometryImportError("The GeoJSON features property is not an array.")
                continue
            buffer = buffer[array_at + 1 :]
            found_array = True

        while True:
            buffer = buffer.lstrip()
            if buffer.startswith("]"):
                return
            if buffer.startswith(","):
                buffer = buffer[1:].lstrip()
            while True:
                try:
                    item, end = decoder.raw_decode(buffer)
                    break
                except JSONDecodeError as exc:
                    chunk = handle.read(1024 * 1024)
                    if not chunk:
                        raise GeometryImportError("The GeoJSON features array is truncated or invalid.") from exc
                    buffer += chunk
                    if len(buffer) > 64 * 1024 * 1024:
                        raise GeometryImportError("A single GeoJSON feature exceeds the 64 MB safety limit.") from exc
            if not isinstance(item, dict) or item.get("type") != "Feature":
                raise GeometryImportError("Every item in the features array must be a GeoJSON Feature.")
            yield item
            buffer = buffer[end:]


def _validate_position(node: object, bounds: list[float]) -> int:
    if not isinstance(node, list) or not node:
        raise GeometryImportError("Geometry coordinates must be non-empty arrays.")
    if all(isinstance(value, int | float) and not isinstance(value, bool) for value in node):
        if len(node) < 2:
            raise GeometryImportError("A coordinate position must contain longitude and latitude.")
        longitude, latitude = float(node[0]), float(node[1])
        if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
            raise GeometryImportError("Coordinates must use WGS84 longitude/latitude ranges.")
        bounds[0] = min(bounds[0], longitude)
        bounds[1] = min(bounds[1], latitude)
        bounds[2] = max(bounds[2], longitude)
        bounds[3] = max(bounds[3], latitude)
        return 1
    return sum(_validate_position(child, bounds) for child in node)


def _is_position(value: object) -> bool:
    return bool(
        isinstance(value, list)
        and len(value) >= 2
        and all(isinstance(item, int | float) and not isinstance(item, bool) for item in value)
    )


def _validate_ring(value: object) -> None:
    if not isinstance(value, list) or len(value) < 4 or not all(_is_position(item) for item in value):
        raise GeometryImportError("A polygon ring must contain at least four coordinate positions.")
    if value[0][:2] != value[-1][:2]:
        raise GeometryImportError("Polygon rings must be closed.")


def _validate_geometry_shape(kind: str, coordinates: object) -> None:
    if kind == "Point":
        if not _is_position(coordinates):
            raise GeometryImportError("Point geometry must contain one coordinate position.")
        return
    if kind == "MultiPoint":
        if not isinstance(coordinates, list) or not coordinates or not all(_is_position(item) for item in coordinates):
            raise GeometryImportError("MultiPoint geometry must contain coordinate positions.")
        return
    polygons = [coordinates] if kind == "Polygon" else coordinates
    if not isinstance(polygons, list) or not polygons:
        raise GeometryImportError(f"{kind} geometry must contain polygon coordinates.")
    for polygon in polygons:
        if not isinstance(polygon, list) or not polygon:
            raise GeometryImportError("Every polygon must contain at least one ring.")
        for ring in polygon:
            _validate_ring(ring)


def validate_geometry(value: object) -> tuple[dict, list[float], int]:
    if not isinstance(value, dict):
        raise GeometryImportError("Feature geometry must be an object.")
    kind = value.get("type")
    if kind not in {"Polygon", "MultiPolygon", "Point", "MultiPoint"}:
        raise GeometryImportError(f"Unsupported geometry type: {kind!r}.")
    _validate_geometry_shape(kind, value.get("coordinates"))
    bounds = [180.0, 90.0, -180.0, -90.0]
    count = _validate_position(value.get("coordinates"), bounds)
    return {"type": kind, "coordinates": value["coordinates"]}, bounds, count


def _district_ancestor_name(session: Session, unit: OrgUnit) -> str | None:
    for ancestor in ancestors(session, unit):
        if ancestor.level_type in {OrgUnitLevel.DISTRICT.value, OrgUnitLevel.CITY.value}:
            return _normalise_name(ancestor.name)
    return None


# DHIS2 names districts "Abim District" while the boundary source names them "ABIM". The suffix is
# a naming convention of the unit type, so a district (never a city) is also indexed without it.
_DISTRICT_SUFFIX = " district"


def prepare_geometry_import(
    session: Session,
    path: Path,
    level_type: str,
    aliases: dict[str, str] | None = None,
) -> GeometryImportPlan:
    """Match boundary features to organisation units by exact normalised name.

    ``aliases`` maps a feature name to the full name of one organisation unit, for spellings the
    owner has approved (for example LUWEERO to Luwero District). Each alias must resolve to exactly
    one candidate unit or the plan is refused; nothing is matched approximately.
    """
    if level_type not in {OrgUnitLevel.DISTRICT.value, OrgUnitLevel.SUB_COUNTY.value}:
        raise GeometryImportError("Only district and sub_county boundary imports are supported.")
    resolved = path.resolve(strict=True)
    candidates = list(
        session.scalars(
            select(OrgUnit).where(
                OrgUnit.active.is_(True),
                OrgUnit.level_type.in_(
                    [OrgUnitLevel.DISTRICT.value, OrgUnitLevel.CITY.value]
                    if level_type == OrgUnitLevel.DISTRICT.value
                    else [OrgUnitLevel.SUB_COUNTY.value]
                ),
            )
        ).all()
    )
    index: dict[tuple[str, ...], list[OrgUnit]] = {}
    for unit in candidates:
        if level_type == OrgUnitLevel.DISTRICT.value:
            name = _normalise_name(unit.name)
            index.setdefault((name,), []).append(unit)
            if unit.level_type == OrgUnitLevel.DISTRICT.value and name.endswith(_DISTRICT_SUFFIX):
                stripped = name[: -len(_DISTRICT_SUFFIX)]
                if stripped:
                    index.setdefault((stripped,), []).append(unit)
        else:
            key = (_district_ancestor_name(session, unit) or "", _normalise_name(unit.name))
            index.setdefault(key, []).append(unit)
    alias_targets: dict[str, OrgUnit] = {}
    for feature_name, unit_name in (aliases or {}).items():
        targets = [unit for unit in candidates if _normalise_name(unit.name) == _normalise_name(unit_name)]
        if len(targets) != 1:
            raise GeometryImportError(
                f"Alias {feature_name!r} -> {unit_name!r} must name exactly one active unit at this level; "
                f"found {len(targets)}."
            )
        alias_targets[_normalise_name(feature_name)] = targets[0]

    plan = GeometryImportPlan(
        source_path=resolved,
        level_type=level_type,
        source_sha256=source_sha256(resolved),
    )
    target_counts: dict[UUID, int] = {}
    for feature_index, feature in enumerate(iter_geojson_features(resolved), start=1):
        plan.total_features += 1
        properties = feature.get("properties") or {}
        if level_type == OrgUnitLevel.DISTRICT.value:
            feature_name = str(properties.get("District") or "").strip()
            district_name = feature_name
            key = (_normalise_name(feature_name),)
        else:
            feature_name = str(properties.get("Sub_County") or "").strip()
            district_name = str(properties.get("District") or "").strip()
            key = (_normalise_name(district_name), _normalise_name(feature_name))
        if not feature_name or (level_type == OrgUnitLevel.SUB_COUNTY.value and not district_name):
            plan.invalid.append({"feature": feature_index, "reason": "required_name_property_missing"})
            continue
        try:
            geometry, _bounds, _points = validate_geometry(feature.get("geometry"))
        except GeometryImportError as exc:
            plan.invalid.append({"feature": feature_index, "name": feature_name, "reason": str(exc)})
            continue
        matches = index.get(key, [])
        if not matches and level_type == OrgUnitLevel.DISTRICT.value and key[0] in alias_targets:
            matches = [alias_targets[key[0]]]
            plan.aliases_applied.append({"feature": feature_name, "org_unit_code": matches[0].code})
        if not matches:
            plan.unmatched.append({"feature": feature_index, "name": feature_name, "district": district_name})
            continue
        if len(matches) != 1:
            plan.ambiguous.append(
                {
                    "feature": feature_index,
                    "name": feature_name,
                    "district": district_name,
                    "org_unit_codes": sorted(unit.code for unit in matches),
                }
            )
            continue
        unit = matches[0]
        target_counts[unit.id] = target_counts.get(unit.id, 0) + 1
        plan.records.append(
            GeometryImportRecord(
                org_unit_id=unit.id,
                org_unit_code=unit.code,
                feature_name=feature_name,
                geometry=geometry,
            )
        )
    duplicate_ids = {unit_id for unit_id, count in target_counts.items() if count > 1}
    plan.duplicate_org_unit_codes = sorted(
        record.org_unit_code for record in plan.records if record.org_unit_id in duplicate_ids
    )
    return plan


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


def boundary_authority(session: Session, plan: GeometryImportPlan):
    """The hierarchy authority that governs activating this plan's level."""
    from app.services.hierarchy_authority import (
        DISTRICT_CITY_COHORT,
        LEVEL_DISTRICT,
        PURPOSE_BOUNDARY,
        hierarchy_authority,
    )

    required = DISTRICT_CITY_COHORT if plan.level_type == LEVEL_DISTRICT else max(plan.total_features, 1)
    return hierarchy_authority(session, purpose=PURPOSE_BOUNDARY, level=plan.level_type, required_units=required)


def boundary_crosswalk_semantics(plan: GeometryImportPlan, authority) -> dict:
    """Separate what reconciled by name from what may become a production boundary mapping.

    Nothing is production-resolved unless the hierarchy for this level is authoritative; until
    then every source feature is production-unresolved and name matches are only candidates.
    """
    duplicates = set(plan.duplicate_org_unit_codes)
    clean = [record for record in plan.records if record.org_unit_code not in duplicates]
    resolved = len(clean) if authority.authoritative else 0
    return {
        **authority.as_dict(),
        "source_features": plan.total_features,
        "reconciliation_matched": len(plan.records),
        "reconciliation_unmatched": len(plan.unmatched),
        "ambiguous": len(plan.ambiguous),
        "invalid": len(plan.invalid),
        "duplicate_targets": len(duplicates),
        "production_resolved": resolved,
        "production_unresolved": plan.total_features - resolved,
        "non_production_candidates": []
        if authority.authoritative
        else sorted({record.feature_name for record in plan.records}),
    }


def _require_reference(value: str | None, code: str, message: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        raise AuthorizationError(code, message)
    return cleaned


def apply_geometry_import(
    session: Session,
    user: User,
    plan: GeometryImportPlan,
    *,
    valid_from: date,
    effective_date_verified: bool = False,
    effective_date_reference: str | None = None,
    mapping_decision_reference: str | None = None,
    allow_unmatched: bool = False,
    partial_activation_reference: str | None = None,
) -> dict:
    """Activate boundary geometry only under recorded owner authority.

    Every condition is checked independently, before any row changes:

    - the caller holds ``manage_mappings``;
    - the hierarchy for this purpose and level is authoritative (approval reference configured and a
      complete cohort present), so synthetic fixtures can never become production boundaries;
    - every matched organisation unit is at the plan's level (no cross-level substitution);
    - the mapping is unambiguous, free of invalid features and duplicate targets, and a mapping
      decision reference is recorded;
    - the source checksum is present;
    - the effective date is confirmed (``effective_date_verified``) **and** its approval reference is
      recorded: the flag confirms a recorded approval, it does not create one;
    - unmatched features are allowed only with ``allow_unmatched`` and a recorded partial-activation
      approval reference; neither bypasses hierarchy approval.
    """
    from app.services.hierarchy_authority import LEVEL_TYPES

    require_action(session, user, ActionPermission.MANAGE_MAPPINGS)
    if plan.level_type not in LEVEL_TYPES:
        raise AuthorizationError("boundary_level_unsupported", "Only district and sub-county boundaries are supported.")
    authority = boundary_authority(session, plan)
    if not authority.authoritative:
        raise AuthorizationError(
            "boundary_hierarchy_not_approved",
            "The organisation-unit hierarchy for this boundary level is not owner-approved and complete, "
            "so no geometry can be activated.",
        )
    if len(plan.source_sha256 or "") != 64:
        raise AuthorizationError("boundary_checksum_missing", "The source file checksum is not recorded.")
    reference = _require_reference(
        effective_date_reference,
        "boundary_effective_date_unverified",
        "The boundary effective date has no recorded owner approval reference, so geometry cannot be activated.",
    )
    if not effective_date_verified:
        raise AuthorizationError(
            "boundary_effective_date_unverified",
            "The boundary effective date is not confirmed against its approval reference.",
        )
    mapping_reference = _require_reference(
        mapping_decision_reference,
        "boundary_mapping_decision_missing",
        "No feature-to-organisation-unit mapping decision is recorded.",
    )
    if not plan.records:
        raise AuthorizationError("invalid_input", "The geometry import did not match any organisation units.")
    if plan.invalid or plan.ambiguous or plan.duplicate_org_unit_codes:
        raise AuthorizationError(
            "boundary_mapping_ambiguous",
            "Invalid, ambiguous or duplicate feature mappings exist; no rows were changed.",
        )
    partial_reference = None
    if plan.unmatched:
        if not allow_unmatched:
            raise AuthorizationError(
                "boundary_mapping_incomplete", "Unmatched geometry features exist; no rows were changed."
            )
        partial_reference = _require_reference(
            partial_activation_reference,
            "boundary_partial_activation_unapproved",
            "Partial boundary activation needs a recorded owner approval reference.",
        )
    allowed_levels = set(LEVEL_TYPES[plan.level_type])
    for record in plan.records:
        unit = session.get(OrgUnit, record.org_unit_id)
        if unit is None or not unit.active or unit.level_type not in allowed_levels:
            raise AuthorizationError(
                "boundary_level_mismatch",
                "A feature maps to an organisation unit outside the approved geography level.",
            )

    source = f"{plan.source_path.name}:sha256:{plan.source_sha256}"
    inserted = 0
    unchanged = 0
    superseded = 0
    for record in plan.records:
        current = session.scalar(
            select(Geometry)
            .where(
                Geometry.org_unit_id == record.org_unit_id,
                Geometry.valid_to.is_(None),
            )
            .order_by(Geometry.valid_from.desc().nulls_last(), Geometry.created_at.desc().nulls_last())
            .with_for_update()
        )
        if current is not None and current.source == source and current.geojson == record.geometry:
            unchanged += 1
            continue
        if current is not None:
            if current.valid_from and current.valid_from >= valid_from:
                raise AuthorizationError(
                    "invalid_input",
                    f"Geometry for {record.org_unit_code} already starts on or after the requested date.",
                )
            current.valid_to = valid_from - timedelta(days=1)
            superseded += 1
        others_query = select(Geometry).where(Geometry.org_unit_id == record.org_unit_id)
        if current is not None:
            others_query = others_query.where(Geometry.id != current.id)
        others = session.scalars(others_query).all()
        for existing in others:
            if intervals_overlap(existing.valid_from, existing.valid_to, valid_from, None):
                raise AuthorizationError(
                    "invalid_input",
                    f"Geometry for {record.org_unit_code} overlaps an existing validity interval.",
                )
        session.add(
            Geometry(
                org_unit_id=record.org_unit_id,
                geojson=record.geometry,
                geometry_kind=str(record.geometry["type"]).casefold(),
                source=source,
                valid_from=valid_from,
            )
        )
        inserted += 1
    write_audit(
        session,
        actor_user_id=user.id,
        action="geometry_imported",
        resource_type="geometry_dataset",
        resource_id=plan.source_sha256,
        after={
            "source_file": plan.source_path.name,
            "source_sha256": plan.source_sha256,
            "level_type": plan.level_type,
            "hierarchy_approval_reference": authority.approval_reference,
            "mapping_decision_reference": mapping_reference,
            "effective_date": valid_from.isoformat(),
            "effective_date_reference": reference,
            "partial_activation_reference": partial_reference,
            "matched": len(plan.records),
            "inserted": inserted,
            "unchanged": unchanged,
            "superseded": superseded,
            "unmatched": len(plan.unmatched),
            "aliases_applied": plan.aliases_applied,
        },
        commit=False,
    )
    session.flush()
    return {"inserted": inserted, "unchanged": unchanged, "superseded": superseded}


SIMPLIFY_VERSION = "hpip-rdp-1"
SIMPLIFY_EPSILON_DEGREES = 0.01


def _point_distance(start: list[float], end: list[float], point: list[float]) -> float:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    if dx == 0 and dy == 0:
        return ((point[0] - start[0]) ** 2 + (point[1] - start[1]) ** 2) ** 0.5
    length = ((dx * dx) + (dy * dy)) ** 0.5
    t = max(
        0.0,
        min(1.0, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / (length * length)),
    )
    proj_x = start[0] + t * dx
    proj_y = start[1] + t * dy
    return ((point[0] - proj_x) ** 2 + (point[1] - proj_y) ** 2) ** 0.5


def simplify_ring(coords: list, epsilon: float = SIMPLIFY_EPSILON_DEGREES) -> list:
    if len(coords) <= 4:
        return [list(point) for point in coords]
    closed = coords[0] == coords[-1]
    working = [list(point) for point in (coords[:-1] if closed else coords)]

    def _rdp(points: list[list[float]]) -> list[list[float]]:
        if len(points) < 3:
            return points
        start, end = points[0], points[-1]
        farthest_index = 0
        farthest = 0.0
        for index, point in enumerate(points[1:-1], start=1):
            distance = _point_distance(start, end, point)
            if distance > farthest:
                farthest = distance
                farthest_index = index
        if farthest > epsilon:
            left = _rdp(points[: farthest_index + 1])
            right = _rdp(points[farthest_index:])
            return left[:-1] + right
        return [start, end]

    simplified = _rdp(working)
    if closed:
        if simplified[0] != simplified[-1]:
            simplified.append(list(simplified[0]))
        if len(simplified) < 4:
            return [list(point) for point in coords]
    return simplified


def simplify_geojson(geometry: dict | None, epsilon: float = SIMPLIFY_EPSILON_DEGREES) -> dict | None:
    if not geometry:
        return geometry
    kind = geometry.get("type")
    if kind == "Polygon":
        return {
            "type": "Polygon",
            "coordinates": [simplify_ring(ring, epsilon) for ring in geometry.get("coordinates") or []],
        }
    if kind == "MultiPolygon":
        return {
            "type": "MultiPolygon",
            "coordinates": [
                [simplify_ring(ring, epsilon) for ring in polygon] for polygon in geometry.get("coordinates") or []
            ],
        }
    return geometry


# Simplified copies of stored geometry, by geometry row ID. A boundary change always creates a new
# geometry row, so an entry can never go stale; the size bound only limits memory.
_SIMPLIFIED_CACHE: dict[tuple[UUID, str], dict | None] = {}
_SIMPLIFIED_CACHE_LIMIT = 20000


def _simplified(row: Geometry) -> dict | None:
    key = (row.id, SIMPLIFY_VERSION)
    if key not in _SIMPLIFIED_CACHE:
        if len(_SIMPLIFIED_CACHE) >= _SIMPLIFIED_CACHE_LIMIT:
            _SIMPLIFIED_CACHE.clear()
        _SIMPLIFIED_CACHE[key] = simplify_geojson(row.geojson)
    return _SIMPLIFIED_CACHE[key]


def _geometries_in_force(
    session: Session, unit_ids: list[UUID], effective_date: date, *, with_geojson: bool = True
) -> dict[UUID, Geometry]:
    query = select(Geometry)
    if not with_geojson:
        # Only which geometry is in force is needed; the shapes are large and are not read.
        query = query.options(defer(Geometry.geojson))
    rows = session.scalars(
        query
        .where(
            Geometry.org_unit_id.in_(unit_ids),
            or_(Geometry.valid_from.is_(None), Geometry.valid_from <= effective_date),
            or_(Geometry.valid_to.is_(None), Geometry.valid_to >= effective_date),
        )
        .order_by(Geometry.valid_from.desc().nulls_last(), Geometry.created_at.desc().nulls_last())
    ).all()
    current: dict[UUID, Geometry] = {}
    for row in rows:
        current.setdefault(row.org_unit_id, row)
    return current


def _geometry_version(row: Geometry) -> dict:
    return {
        "geometry_id": str(row.id),
        "valid_from": row.valid_from.isoformat() if row.valid_from else None,
        "valid_to": row.valid_to.isoformat() if row.valid_to else None,
        "source": row.source,
        "geometry_kind": row.geometry_kind,
    }


def build_map_block(
    session: Session,
    user: User,
    *,
    parent: OrgUnit,
    value_rows: list[dict],
    indicator_code: str | None,
    effective_date: date,
) -> dict:
    """Define the map cohort from the same authorised value rows the screen shows.

    Every rendered feature corresponds to exactly one value row. Geometry from another
    administrative level is never substituted: if the value rows are regions and only
    district boundaries exist, the map reports that region geometry is unavailable.
    """
    rows_by_id: dict[str, dict] = {}
    for row in value_rows:
        unit = session.get(OrgUnit, UUID(str(row["org_unit_id"])))
        if unit is None or not unit.active or not can_access_org_unit(session, user, unit):
            continue
        rows_by_id[str(unit.id)] = {**row, "_unit": unit}
    units = [row["_unit"] for row in rows_by_id.values()]
    level_types = sorted({unit.level_type for unit in units})
    classes = sorted({cls.value for unit in units if (cls := aggregation_class(unit.level_type))})
    geometries = (
        _geometries_in_force(session, [unit.id for unit in units], effective_date, with_geojson=False) if units else {}
    )
    feature_ids = [str(unit.id) for unit in units if unit.id in geometries]
    missing_geometry = [str(unit.id) for unit in units if unit.id not in geometries]
    missing_values = [
        key
        for key, row in rows_by_id.items()
        if ((row.get("values") or {}).get(indicator_code or "") or {}).get("raw_value") is None
    ]
    if not units:
        state, note = "no_map_units", "No authorised units are available for this map level."
    elif len(classes) > 1:
        state = "mixed_levels_not_mapped"
        note = "The value rows span different administrative levels and are not mapped."
        feature_ids = []
    elif feature_ids:
        state, note = "mapped", None
    else:
        level_label = ", ".join(level_types)
        state = "geometry_unavailable_for_level"
        note = (
            f"No approved boundaries or coordinates are available for {level_label} units effective "
            f"{effective_date.isoformat()}. Shapes from another administrative level are not substituted."
        )
    return {
        "map_state": state,
        "mapping_note": note,
        "map_level": classes[0] if len(classes) == 1 else None,
        "map_level_types": level_types,
        "map_parent_org_unit_id": str(parent.id),
        "map_feature_org_unit_ids": feature_ids,
        "selected_indicator": indicator_code,
        "map_value_run_ids": {
            key: row.get("calculation_run_id") for key, row in rows_by_id.items() if key in feature_ids
        },
        "geometry_effective_date": effective_date.isoformat(),
        "geometry_versions": {key: _geometry_version(geometries[UUID(key)]) for key in feature_ids},
        "missing_geometry_ids": missing_geometry,
        "missing_value_ids": missing_values,
    }


def snapshot_map_features(
    session: Session,
    user: User,
    *,
    map_block: dict,
    value_rows: list[dict],
    simplify: bool = False,
) -> dict:
    """GeoJSON for exactly the snapshot's map cohort, with values copied from the snapshot."""
    indicator_code = map_block.get("selected_indicator")
    effective_date = date.fromisoformat(map_block["geometry_effective_date"])
    wanted = [UUID(item) for item in map_block.get("map_feature_org_unit_ids") or []]
    rows_by_id = {str(row["org_unit_id"]): row for row in value_rows}
    authorised: list[OrgUnit] = []
    for unit_id in wanted:
        unit = session.get(OrgUnit, unit_id)
        if unit is not None and unit.active and can_access_org_unit(session, user, unit):
            authorised.append(unit)
    geometries = (
        _geometries_in_force(session, [unit.id for unit in authorised], effective_date, with_geojson=not simplify)
        if authorised
        else {}
    )
    features = []
    for unit in authorised:
        geometry = geometries.get(unit.id)
        row = rows_by_id.get(str(unit.id))
        if geometry is None or row is None:
            continue
        value = (row.get("values") or {}).get(indicator_code or "") or {}
        features.append(
            {
                "type": "Feature",
                "id": str(unit.id),
                "properties": {
                    "org_unit_id": str(unit.id),
                    "code": unit.code,
                    "name": unit.name,
                    "level_type": unit.level_type,
                    "parent_id": str(unit.parent_id) if unit.parent_id else None,
                    "indicator_code": indicator_code,
                    "raw_value": value.get("raw_value"),
                    "display_value": value.get("display_value"),
                    "unit": value.get("unit"),
                    "status": value.get("status"),
                    "quality_status": value.get("quality_status"),
                    "calculation_run_id": row.get("calculation_run_id"),
                },
                "geometry": _simplified(geometry) if simplify else geometry.geojson,
            }
        )
    return {
        "type": "FeatureCollection",
        "map_state": map_block.get("map_state"),
        "mapping_note": map_block.get("mapping_note"),
        "map_level": map_block.get("map_level"),
        "selected_indicator": indicator_code,
        "geometry_effective_date": map_block.get("geometry_effective_date"),
        "feature_count": len(features),
        "missing_geometry_ids": map_block.get("missing_geometry_ids") or [],
        "missing_value_ids": map_block.get("missing_value_ids") or [],
        "features": features,
    }


def map_feature_collection(
    session: Session,
    user: User,
    selected: OrgUnit,
    *,
    as_of: date | None = None,
    simplify: bool = False,
    include_features: bool = True,
) -> dict:
    """Boundaries for the nearest mapped level below ``selected``.

    ``include_features=False`` returns the same metadata without reading any shapes.
    """
    effective_date = as_of or date.today()
    units = [
        unit for unit in descendants(session, selected, include_self=True) if can_access_org_unit(session, user, unit)
    ]
    ids = [unit.id for unit in units]
    geometry_query = select(Geometry)
    if not include_features or simplify:
        geometry_query = geometry_query.options(defer(Geometry.geojson))
    geometry_rows = session.scalars(
        geometry_query
        .where(
            Geometry.org_unit_id.in_(ids),
            or_(Geometry.valid_from.is_(None), Geometry.valid_from <= effective_date),
            or_(Geometry.valid_to.is_(None), Geometry.valid_to >= effective_date),
        )
        .order_by(Geometry.valid_from.desc().nulls_last(), Geometry.created_at.desc().nulls_last())
    ).all()
    current_by_unit: dict[UUID, Geometry] = {}
    for row in geometry_rows:
        current_by_unit.setdefault(row.org_unit_id, row)

    selected_rank = ORG_UNIT_LEVEL_RANK.get(OrgUnitLevel(selected.level_type), 99)
    available_ranks = sorted(
        {
            ORG_UNIT_LEVEL_RANK.get(OrgUnitLevel(unit.level_type), 99)
            for unit in units
            if unit.id in current_by_unit and ORG_UNIT_LEVEL_RANK.get(OrgUnitLevel(unit.level_type), 99) > selected_rank
        }
    )
    render_rank = available_ranks[0] if available_ranks else selected_rank
    target_units = [unit for unit in units if ORG_UNIT_LEVEL_RANK.get(OrgUnitLevel(unit.level_type), 99) == render_rank]
    mapped_units = [unit for unit in target_units if unit.id in current_by_unit]
    features = []
    for unit in mapped_units if include_features else []:
        row = current_by_unit[unit.id]
        features.append(
            {
                "type": "Feature",
                "id": str(unit.id),
                "properties": {
                    "org_unit_id": str(unit.id),
                    "code": unit.code,
                    "name": unit.name,
                    "level_type": unit.level_type,
                    "parent_id": str(unit.parent_id) if unit.parent_id else None,
                    "valid_from": row.valid_from.isoformat() if row.valid_from else None,
                    "valid_to": row.valid_to.isoformat() if row.valid_to else None,
                },
                "geometry": (_simplified(row) if simplify else row.geojson),
            }
        )
    awaiting_mapping = len(mapped_units) == 0
    return {
        "type": "FeatureCollection",
        "selected_org_unit": {
            "id": str(selected.id),
            "code": selected.code,
            "name": selected.name,
            "level_type": selected.level_type,
        },
        "render_levels": sorted({unit.level_type for unit in target_units}),
        "effective_date": effective_date.isoformat(),
        "feature_count": len(mapped_units),
        "eligible_unit_count": len(target_units),
        "mapping_state": ("mapped" if mapped_units else "boundaries_awaiting_approved_mapping"),
        "simplify_applied": simplify,
        "simplify_version": SIMPLIFY_VERSION if simplify else None,
        "mapping_note": (
            "Authoritative boundaries are not applied. Production import remains blocked "
            "until the approved analytical hierarchy, feature-to-org-unit mappings, and "
            "effective date are supplied to a manage_mappings user."
            if awaiting_mapping
            else None
        ),
        "unmapped_units": [
            {"id": str(unit.id), "code": unit.code, "name": unit.name, "level_type": unit.level_type}
            for unit in target_units
            if unit.id not in current_by_unit
        ],
        "features": features,
    }

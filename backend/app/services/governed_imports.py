"""Fail-closed application of owner-approved hierarchy and aggregate mapping packets.

Discovery and proposal files are evidence, never configuration. These services accept only an
explicitly reviewed packet, enforce two-person application, preserve validity intervals and write
one audit record for the atomic change. Callers own the transaction.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import ActionPermission, MappingSourceSystem, OrgUnitLevel
from app.models import OrgUnit, OrgUnitMapping, Programme, SourceMapping, User
from app.services.audit import write_audit
from app.services.authorization import AuthorizationError, has_action
from app.services.geography import reject_overlapping_org_unit_mappings
from app.services.mapping_coverage import evaluate_coverage
from app.services.mappings import SUPPORTED_AGGREGATION_SEMANTICS, select_aggregate_mappings

DHIS2_UID = re.compile(r"^[A-Za-z][A-Za-z0-9]{10}$")
INTERNAL_CODE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
HIERARCHY_SCHEMA = "hpip.hierarchy-approval.v1"
SOURCE_MAPPING_SCHEMA = "hpip.source-mapping-approval.v1"


class GovernedImportError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class ImportResult:
    created: int
    unchanged: int
    packet_sha256: str
    coverage: dict[str, dict] | None = None

    def as_dict(self) -> dict:
        return {
            "created": self.created,
            "unchanged": self.unchanged,
            "packet_sha256": self.packet_sha256,
            "coverage": self.coverage,
        }


def _packet_sha256(packet: dict) -> str:
    payload = json.dumps(packet, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _as_date(value: object, field: str) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise GovernedImportError("invalid_date", f"{field} must be an ISO date.") from exc


def _date_range(row: dict, *, prefix: str) -> tuple[date | None, date | None]:
    valid_from = _as_date(row.get("valid_from"), f"{prefix}.valid_from")
    valid_to = _as_date(row.get("valid_to"), f"{prefix}.valid_to")
    if valid_from and valid_to and valid_to < valid_from:
        raise GovernedImportError(
            "invalid_date_range", f"{prefix}.valid_to cannot precede valid_from."
        )
    return valid_from, valid_to


def _authorise_two_people(session: Session, actor: User, reviewer: User) -> None:
    if actor.id == reviewer.id:
        raise GovernedImportError(
            "separation_of_duties_required",
            "The applying user and approving reviewer must be different people.",
        )
    if not actor.is_active or not reviewer.is_active:
        raise GovernedImportError("inactive_user", "Both the applying user and reviewer must be active.")
    for user, label in ((actor, "applying user"), (reviewer, "reviewer")):
        if not has_action(session, user, ActionPermission.MANAGE_MAPPINGS):
            raise GovernedImportError(
                "forbidden_action", f"The {label} must have manage_mappings permission."
            )


def _validate_packet_header(packet: dict, *, schema: str, approval_reference: str) -> list[dict]:
    if packet.get("schema") != schema:
        raise GovernedImportError("invalid_schema", f"Expected packet schema {schema!r}.")
    recorded = str(packet.get("approval_reference") or "").strip()
    supplied = approval_reference.strip()
    if not supplied or recorded != supplied:
        raise GovernedImportError(
            "approval_reference_mismatch",
            "The non-empty command approval reference must exactly match the reviewed packet.",
        )
    rows = packet.get("rows")
    if not isinstance(rows, list) or not rows:
        raise GovernedImportError("empty_packet", "The approval packet contains no rows.")
    if any(not isinstance(row, dict) for row in rows):
        raise GovernedImportError("invalid_row", "Every packet row must be a JSON object.")
    if any(row.get("review_status") != "approved" for row in rows):
        raise GovernedImportError("unapproved_row", "Every packet row must be explicitly approved.")
    return rows


def apply_hierarchy_packet(
    session: Session,
    *,
    packet: dict,
    actor: User,
    reviewer: User,
    approval_reference: str,
) -> ImportResult:
    """Create only explicitly approved internal units and DHIS2 mappings; never guess or overwrite."""
    _authorise_two_people(session, actor, reviewer)
    rows = _validate_packet_header(
        packet, schema=HIERARCHY_SCHEMA, approval_reference=approval_reference
    )
    codes = [str(row.get("code") or "").strip() for row in rows]
    if any(not INTERNAL_CODE.fullmatch(code) for code in codes) or len(codes) != len(set(codes)):
        raise GovernedImportError(
            "invalid_code", "Hierarchy row codes must be safe, non-empty and unique."
        )
    valid_levels = {item.value for item in OrgUnitLevel}
    known = {row.code: row for row in session.scalars(select(OrgUnit)).all()}
    pending = {code: row for code, row in zip(codes, rows, strict=True)}
    created = unchanged = 0
    while pending:
        progressed = False
        for code, row in list(pending.items()):
            name = str(row.get("name") or "").strip()
            level = str(row.get("level_type") or "").strip()
            parent_code = str(row.get("parent_code") or "").strip() or None
            uid = str(row.get("dhis2_uid") or "").strip()
            if not name or level not in valid_levels or not DHIS2_UID.fullmatch(uid):
                raise GovernedImportError(
                    "invalid_hierarchy_row",
                    f"Hierarchy row {code!r} needs a name, supported level and valid DHIS2 UID.",
                )
            if (level == OrgUnitLevel.COUNTRY.value) != (parent_code is None):
                raise GovernedImportError(
                    "invalid_hierarchy_root",
                    "Only the country may omit a parent, and the country must omit it.",
                )
            if parent_code and parent_code not in known:
                continue
            parent = known.get(parent_code) if parent_code else None
            expected_path = f"{parent.path.rstrip('/')}/{code}" if parent else f"/{code}"
            unit = known.get(code)
            unit_valid_from, unit_valid_to = _date_range(row, prefix=code)
            if unit is None:
                if level == OrgUnitLevel.COUNTRY.value and session.scalar(
                    select(OrgUnit.id).where(
                        OrgUnit.level_type == OrgUnitLevel.COUNTRY.value,
                        OrgUnit.active.is_(True),
                    )
                ):
                    raise GovernedImportError(
                        "country_already_exists", "An active country already exists."
                    )
                unit = OrgUnit(
                    code=code,
                    name=name,
                    level_type=level,
                    parent_id=parent.id if parent else None,
                    path=expected_path,
                    active=True,
                    valid_from=unit_valid_from,
                    valid_to=unit_valid_to,
                )
                session.add(unit)
                session.flush()
                known[code] = unit
                created += 1
            elif (
                unit.name != name
                or unit.level_type != level
                or unit.parent_id != (parent.id if parent else None)
                or unit.path != expected_path
                or not unit.active
                or unit.valid_from != unit_valid_from
                or unit.valid_to != unit_valid_to
            ):
                raise GovernedImportError(
                    "hierarchy_conflict",
                    f"Existing organisation unit {code!r} differs from the approved packet.",
                )
            else:
                unchanged += 1
            mapping_dates = {
                "valid_from": row.get("mapping_valid_from"),
                "valid_to": row.get("mapping_valid_to"),
            }
            valid_from, valid_to = _date_range(mapping_dates, prefix=f"{code}.mapping")
            exact = session.scalar(
                select(OrgUnitMapping).where(
                    OrgUnitMapping.source_system == MappingSourceSystem.DHIS2.value,
                    OrgUnitMapping.external_uid == uid,
                    OrgUnitMapping.org_unit_id == unit.id,
                    OrgUnitMapping.valid_from.is_(None)
                    if valid_from is None
                    else OrgUnitMapping.valid_from == valid_from,
                    OrgUnitMapping.valid_to.is_(None)
                    if valid_to is None
                    else OrgUnitMapping.valid_to == valid_to,
                )
            )
            if exact is None:
                mapping = OrgUnitMapping(
                    org_unit_id=unit.id,
                    source_system=MappingSourceSystem.DHIS2.value,
                    external_uid=uid,
                    valid_from=valid_from,
                    valid_to=valid_to,
                )
                try:
                    reject_overlapping_org_unit_mappings(session, mapping)
                except AuthorizationError as exc:
                    raise GovernedImportError(
                        "org_mapping_overlap", exc.message
                    ) from exc
                session.add(mapping)
                session.flush()
            pending.pop(code)
            progressed = True
        if not progressed:
            unresolved = ", ".join(sorted(pending)[:10])
            raise GovernedImportError(
                "missing_parent_or_cycle",
                f"Hierarchy parents are missing or cyclic for: {unresolved}.",
            )
    digest = _packet_sha256(packet)
    write_audit(
        session,
        actor_user_id=actor.id,
        action="approved_hierarchy_packet_applied",
        resource_type="organisation_hierarchy",
        resource_id=digest[:32],
        after={
            "approval_reference": approval_reference,
            "reviewed_by_user_id": str(reviewer.id),
            "packet_sha256": digest,
            "rows": len(rows),
            "created": created,
            "unchanged": unchanged,
        },
    )
    return ImportResult(created=created, unchanged=unchanged, packet_sha256=digest)


def apply_source_mapping_packet(
    session: Session,
    *,
    packet: dict,
    actor: User,
    reviewer: User,
    approval_reference: str,
    mapping_version: str,
) -> ImportResult:
    """Apply reviewed aggregate mappings atomically; incomplete coverage remains non-runnable."""
    _authorise_two_people(session, actor, reviewer)
    rows = _validate_packet_header(
        packet, schema=SOURCE_MAPPING_SCHEMA, approval_reference=approval_reference
    )
    version = mapping_version.strip()
    if not version or len(version) > 40:
        raise GovernedImportError("invalid_mapping_version", "A mapping version of 1-40 characters is required.")
    programmes = {row.code: row for row in session.scalars(select(Programme)).all()}
    created = unchanged = 0
    touched: set[str] = set()
    packet_keys: set[tuple[str, str]] = set()
    for row in rows:
        key = str(row.get("internal_source_key") or "").strip()
        uid = str(row.get("approved_uid") or "").strip()
        item_kind = str(row.get("approved_item_kind") or "").strip()
        semantics = str(row.get("approved_aggregation_semantics") or "").strip().upper()
        programme_codes = row.get("programmes") or []
        if not key or not DHIS2_UID.fullmatch(uid):
            raise GovernedImportError("invalid_mapping_row", "Every row needs a source key and valid approved UID.")
        if item_kind not in {"data_element", "indicator"} or semantics not in (
            SUPPORTED_AGGREGATION_SEMANTICS
        ):
            raise GovernedImportError(
                "mapping_semantics_missing",
                f"Mapping {key!r} needs a supported item kind and aggregation semantics.",
            )
        if not isinstance(programme_codes, list) or any(
            not isinstance(code, str) or not code.strip() for code in programme_codes
        ):
            raise GovernedImportError(
                "programme_invalid", f"Mapping {key!r} needs a list of programme codes."
            )
        if len(programme_codes) != len(set(programme_codes)):
            raise GovernedImportError(
                "programme_duplicate", f"Mapping {key!r} repeats a programme."
            )
        candidate = next((item for item in row.get("candidates") or [] if item.get("uid") == uid), None)
        if candidate is None:
            raise GovernedImportError(
                "approved_uid_not_in_evidence", f"Approved UID for {key!r} is absent from the proposal evidence."
            )
        if candidate.get("item_kind") != item_kind:
            raise GovernedImportError(
                "item_kind_mismatch",
                f"Approved item kind for {key!r} differs from the proposal evidence.",
            )
        coc = str(row.get("approved_category_option_combo") or "").strip() or None
        if coc and not DHIS2_UID.fullmatch(coc):
            raise GovernedImportError(
                "invalid_category_option_combo",
                f"Mapping {key!r} has an invalid category option combo UID.",
            )
        if coc and item_kind != "data_element":
            raise GovernedImportError(
                "category_option_combo_item_kind",
                f"Mapping {key!r} may use a category option combo only with a data element.",
            )
        if candidate.get("requires_category_option_combo") and not coc:
            raise GovernedImportError(
                "category_option_combo_required", f"Mapping {key!r} requires an approved category option combo."
            )
        valid_from, valid_to = _date_range(row, prefix=key)
        if not programme_codes:
            raise GovernedImportError("programme_missing", f"Mapping {key!r} has no programme.")
        for code in programme_codes:
            packet_key = (str(code), key)
            if packet_key in packet_keys:
                raise GovernedImportError(
                    "duplicate_source_mapping",
                    f"The packet repeats mapping {code}/{key!s}.",
                )
            packet_keys.add(packet_key)
            programme = programmes.get(str(code))
            if programme is None or not programme.active:
                raise GovernedImportError("unknown_programme", f"Programme {code!r} is not active.")
            existing = session.scalar(
                select(SourceMapping).where(
                    SourceMapping.internal_source_key == key,
                    SourceMapping.mapping_version == version,
                    SourceMapping.programme_id == programme.id,
                )
            )
            values = (uid, item_kind, coc, semantics, valid_from, valid_to)
            if existing is not None:
                current = (
                    existing.dhis2_item_uid,
                    existing.item_kind,
                    existing.category_option_combo_uid,
                    existing.aggregation_semantics,
                    existing.valid_from,
                    existing.valid_to,
                )
                if current != values or not existing.enabled:
                    raise GovernedImportError(
                        "source_mapping_conflict",
                        f"Existing {code}/{key}/{version} mapping differs from the approved packet.",
                    )
                unchanged += 1
            else:
                session.add(
                    SourceMapping(
                        internal_source_key=key,
                        programme_id=programme.id,
                        dhis2_item_uid=uid,
                        item_kind=item_kind,
                        category_option_combo_uid=coc,
                        aggregation_semantics=semantics,
                        mapping_version=version,
                        enabled=True,
                        notes=f"Approved under {approval_reference}; reviewed by {reviewer.username}.",
                        valid_from=valid_from,
                        valid_to=valid_to,
                    )
                )
                created += 1
            touched.add(programme.code)
    session.flush()
    coverage: dict[str, dict] = {}
    for code in sorted(touched):
        programme = programmes[code]
        # This also rejects within-version UID/key collisions.
        select_aggregate_mappings(
            session, programme_id=programme.id, mapping_version=version
        )
        coverage[code] = evaluate_coverage(
            session, programme_id=programme.id, mapping_version=version
        ).as_dict()
    digest = _packet_sha256(packet)
    write_audit(
        session,
        actor_user_id=actor.id,
        action="approved_source_mapping_packet_applied",
        resource_type="source_mapping_set",
        resource_id=digest[:32],
        after={
            "approval_reference": approval_reference,
            "reviewed_by_user_id": str(reviewer.id),
            "mapping_version": version,
            "packet_sha256": digest,
            "rows": len(rows),
            "created": created,
            "unchanged": unchanged,
            "coverage": coverage,
        },
    )
    return ImportResult(
        created=created,
        unchanged=unchanged,
        packet_sha256=digest,
        coverage=coverage,
    )

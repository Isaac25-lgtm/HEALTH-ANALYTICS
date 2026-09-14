from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import EventFieldMapping, Programme, SourceMapping


class MappingSelectionError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def _in_force(valid_from: date | None, valid_to: date | None, as_of: date | None) -> bool:
    if as_of is None:
        return True
    if valid_from and as_of < valid_from:
        return False
    if valid_to and as_of > valid_to:
        return False
    return True


def select_aggregate_mappings(
    session: Session,
    *,
    programme_id: UUID,
    mapping_version: str,
    as_of: date | None = None,
    item_kind: str | None = None,
    category_option_combo_uid: str | None = None,
) -> list[SourceMapping]:
    query = select(SourceMapping).where(
        SourceMapping.programme_id == programme_id,
        SourceMapping.mapping_version == mapping_version,
        SourceMapping.enabled.is_(True),
    )
    if item_kind:
        query = query.where(SourceMapping.item_kind == item_kind)
    rows = [
        row
        for row in session.scalars(query).all()
        if _in_force(row.valid_from, row.valid_to, as_of)
        and (
            category_option_combo_uid is None
            or (row.category_option_combo_uid or "") == category_option_combo_uid
        )
    ]
    seen_uid: dict[tuple[str, str], str] = {}
    seen_key: dict[str, tuple[str, str]] = {}
    for row in rows:
        if not row.dhis2_item_uid:
            continue
        uid_key = (row.dhis2_item_uid, row.category_option_combo_uid or "")
        if uid_key in seen_uid and seen_uid[uid_key] != row.internal_source_key:
            raise MappingSelectionError(
                "mapping_ambiguous",
                "Enabled mappings collide for the same programme, version, and category context.",
            )
        seen_uid[uid_key] = row.internal_source_key
        if row.internal_source_key in seen_key and seen_key[row.internal_source_key] != uid_key:
            raise MappingSelectionError(
                "mapping_ambiguous",
                "Enabled mappings collide for the same internal source key.",
            )
        seen_key[row.internal_source_key] = uid_key
    return rows


def select_event_mappings(
    session: Session,
    *,
    programme_id: UUID,
    mapping_version: str,
    as_of: date | None = None,
    event_type: str | None = None,
    program_stage_uid: str | None = None,
) -> list[EventFieldMapping]:
    query = select(EventFieldMapping).where(
        EventFieldMapping.programme_id == programme_id,
        EventFieldMapping.mapping_version == mapping_version,
        EventFieldMapping.enabled.is_(True),
    )
    if event_type:
        query = query.where(EventFieldMapping.event_type == event_type)
    if program_stage_uid:
        query = query.where(EventFieldMapping.program_stage_uid == program_stage_uid)
    rows = [row for row in session.scalars(query).all() if _in_force(row.valid_from, row.valid_to, as_of)]
    seen: dict[tuple[str | None, str | None, str | None, str], str] = {}
    for row in rows:
        key = (
            row.program_uid,
            row.program_stage_uid,
            row.source_data_element_uid,
            row.event_type,
        )
        if row.source_data_element_uid and key in seen and seen[key] != row.internal_semantic_field:
            raise MappingSelectionError(
                "mapping_ambiguous",
                "Enabled event mappings collide for the same programme stage and field.",
            )
        if row.source_data_element_uid:
            seen[key] = row.internal_semantic_field
    return rows


def resolve_programme_uid(
    session: Session,
    programme_id: UUID,
    mapping_version: str,
    as_of: date | None = None,
) -> str | None:
    rows = select_event_mappings(
        session,
        programme_id=programme_id,
        mapping_version=mapping_version,
        as_of=as_of,
    )
    uids = {row.program_uid for row in rows if row.program_uid}
    if len(uids) > 1:
        raise MappingSelectionError(
            "mapping_ambiguous",
            "Multiple programme UIDs are mapped for the requested programme.",
        )
    return next(iter(uids), None)


def programme_by_code(session: Session, code: str) -> Programme | None:
    return session.scalar(select(Programme).where(Programme.code == code))

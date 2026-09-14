from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import ProgrammeCode
from app.domain.periods import parse_period
from app.models import EventFieldMapping, Programme, RawEventSnapshot
from app.services.geography import descendants
from app.services.mpdsr import in_death_cohort


def mpdsr_programme(session: Session) -> Programme | None:
    return session.scalar(select(Programme).where(Programme.code == ProgrammeCode.MPDSR.value))


def approved_mpdsr_program_uids(session: Session, as_of=None) -> set[str]:
    programme = mpdsr_programme(session)
    if programme is None:
        return set()
    query = select(EventFieldMapping).where(
        EventFieldMapping.programme_id == programme.id,
        EventFieldMapping.enabled.is_(True),
    )
    uids = {row.program_uid for row in session.scalars(query).all() if row.program_uid}
    return uids


def event_in_mpdsr_scope(session: Session, event: RawEventSnapshot, *, as_of=None) -> bool:
    programme = mpdsr_programme(session)
    if event.programme_id and programme and event.programme_id != programme.id:
        return False
    approved = approved_mpdsr_program_uids(session, as_of=as_of)
    if approved:
        return bool(event.program_uid and event.program_uid in approved)
    if event.program_uid:
        return False
    return True


def scoped_mpdsr_events(
    session: Session,
    org_unit,
    period: str,
    *,
    unit_ids: set[UUID] | None = None,
) -> list[RawEventSnapshot]:
    as_of = parse_period(period).end
    units = unit_ids or {unit.id for unit in descendants(session, org_unit, include_self=True)}
    rows = session.scalars(
        select(RawEventSnapshot).where(
            RawEventSnapshot.org_unit_id.in_(units),
            RawEventSnapshot.is_current.is_(True),
            RawEventSnapshot.source_connector == "tracker",
        )
    ).all()
    return [
        event
        for event in rows
        if event_in_mpdsr_scope(session, event, as_of=as_of) and in_death_cohort(event, period)
    ]

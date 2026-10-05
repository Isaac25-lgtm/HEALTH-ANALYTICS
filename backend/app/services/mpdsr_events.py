from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
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
    if as_of is not None:
        from sqlalchemy import or_

        query = query.where(
            or_(EventFieldMapping.valid_from.is_(None), EventFieldMapping.valid_from <= as_of),
            or_(EventFieldMapping.valid_to.is_(None), EventFieldMapping.valid_to >= as_of),
        )
    uids = {row.program_uid for row in session.scalars(query).all() if row.program_uid}
    return uids


def mpdsr_scope(session: Session, *, as_of=None):
    """The MPDSR scope test with its programme and approved program UIDs resolved once."""
    programme = mpdsr_programme(session)
    approved = approved_mpdsr_program_uids(session, as_of=as_of)

    def check(event: RawEventSnapshot) -> bool:
        if event.programme_id and programme and event.programme_id != programme.id:
            return False
        if approved:
            return bool(event.program_uid and event.program_uid in approved)
        return not event.program_uid

    return check


def event_in_mpdsr_scope(session: Session, event: RawEventSnapshot, *, as_of=None) -> bool:
    return mpdsr_scope(session, as_of=as_of)(event)


def retained_mpdsr_events(
    session: Session,
    org_unit,
    period: str,
    *,
    unit_ids: set[UUID] | None = None,
) -> list[RawEventSnapshot]:
    as_of = parse_period(period).end
    units = (
        unit_ids
        if unit_ids is not None
        else {unit.id for unit in descendants(session, org_unit, include_self=True, period=period)}
    )
    programme = mpdsr_programme(session)
    if programme is None:
        return []
    rows = session.scalars(
        select(RawEventSnapshot).where(
            RawEventSnapshot.org_unit_id.in_(units),
            RawEventSnapshot.is_current.is_(True),
            # Null programme is a compatibility path for old minimised records only;
            # mpdsr_scope below still checks the approved form UID.
            (RawEventSnapshot.programme_id == programme.id) | RawEventSnapshot.programme_id.is_(None),
            RawEventSnapshot.source_connector == "tracker",
            RawEventSnapshot.extracted_at
            > datetime.now(UTC) - timedelta(hours=get_settings().mpdsr_event_retention_hours),
        )
    ).all()
    in_scope = mpdsr_scope(session, as_of=as_of)
    return [event for event in rows if in_scope(event)]


def scoped_mpdsr_events(
    session: Session,
    org_unit,
    period: str,
    *,
    unit_ids: set[UUID] | None = None,
) -> list[RawEventSnapshot]:
    return [
        event
        for event in retained_mpdsr_events(session, org_unit, period, unit_ids=unit_ids)
        if in_death_cohort(event, period)
    ]

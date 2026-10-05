"""Withdraw stale current facts only after a complete, exact-scoped extraction.

Historical rows are retained for lineage. No absence marker or reported zero is invented.
"""

from datetime import UTC, datetime, time, timedelta

from sqlalchemy import and_, or_, select, update

from app.models import OrgUnit, RawAggregateValue, RawEventSnapshot
from app.services.geography import escape_like
from app.services.observability import record_operational_event


def _complete(job) -> bool:
    return bool(
        job.status == "succeeded"
        and job.programme_id is not None
        and bool(job.mapping_version)
        and (job.coverage_manifest or {}).get("complete")
        and not job.cancelled
        and not job.page_limit_reached
        and not job.rejected_count
    )


def reconcile_aggregate_withdrawals(session, job, *, seen_row_ids, scopes) -> int:
    if not _complete(job) or not scopes:
        return 0
    # A creation timestamp may be truncated to seconds by the database. Only
    # the worker's actual attempt start can certify which facts preceded it.
    attempt_started = job.started_at
    if attempt_started is None:
        return 0
    clauses = []
    for scope in scopes:
        if not scope["org_unit_ids"] or not scope["periods"]:
            continue
        clause = and_(
            RawAggregateValue.org_unit_id.in_(scope["org_unit_ids"]),
            RawAggregateValue.period.in_(scope["periods"]),
            RawAggregateValue.internal_source_key == scope["source_key"],
            RawAggregateValue.dhis2_item_uid == scope["item_uid"],
            RawAggregateValue.category_option_combo_uid == (scope.get("category_option_combo_uid") or ""),
        )
        clauses.append(clause)
    if not clauses:
        return 0
    target = session.get(OrgUnit, job.org_unit_id) if job.org_unit_id else None
    if target is None:
        return 0
    subtree = select(OrgUnit.id).where(
        or_(
            OrgUnit.id == target.id,
            OrgUnit.path.like(escape_like(target.path.rstrip("/") + "/") + "%", escape="\\"),
        )
    )
    query = select(RawAggregateValue).where(
        RawAggregateValue.source_system == "dhis2",
        RawAggregateValue.programme_id == job.programme_id,
        RawAggregateValue.mapping_version == job.mapping_version,
        RawAggregateValue.is_current.is_(True),
        # An older in-flight request cannot certify absence of a newer attempt's facts.
        RawAggregateValue.extracted_at <= attempt_started,
        RawAggregateValue.org_unit_id.in_(subtree),
        or_(*clauses),
    )
    # Do not put national-size ID arrays into SQL (SQLite also has a parameter limit).
    # The new rows carry this attempt's IDs; retries of the same job must not protect
    # rows left over from a previous, incomplete attempt merely because job IDs match.
    withdrawn = 0
    at = datetime.now(UTC).isoformat()
    last_id = None
    while True:
        page = query.order_by(RawAggregateValue.id).limit(500)
        if last_id is not None:
            page = page.where(RawAggregateValue.id > last_id)
        rows = session.scalars(page).all()
        if not rows:
            break
        last_id = rows[-1].id
        for row in rows:
            if row.id in seen_row_ids:
                continue
            row.is_current = False
            row.provenance = {
                **(row.provenance or {}),
                "withdrawal_sync_job_id": str(job.id),
                "withdrawn_at": at,
                "withdrawal_reason": "not_returned_in_complete_extract",
            }
            withdrawn += 1
        session.flush()
    job.coverage_manifest = {**job.coverage_manifest, "withdrawn_aggregate_count": withdrawn}
    record_operational_event(
        "aggregate_withdrawals_reconciled", job_id=str(job.id), records_stored=withdrawn, session=session
    )
    return withdrawn


def reconcile_event_withdrawals(session, job, *, seen_row_ids, root_ids, program_uids) -> int:
    if not _complete(job) or not root_ids or not program_uids or not job.window_start or not job.window_end:
        return 0
    attempt_started = job.started_at
    if attempt_started is None:
        return 0
    target = session.get(OrgUnit, job.org_unit_id) if job.org_unit_id else None
    if target is None:
        return 0
    roots = session.scalars(
        select(OrgUnit).where(
            OrgUnit.id.in_(root_ids),
            or_(
                OrgUnit.id == target.id,
                OrgUnit.path.like(escape_like(target.path.rstrip("/") + "/") + "%", escape="\\"),
            ),
        )
    ).all()
    subtree = (
        select(OrgUnit.id).where(
            or_(
                *(
                    or_(
                        OrgUnit.id == root.id,
                        OrgUnit.path.like(escape_like(root.path.rstrip("/") + "/") + "%", escape="\\"),
                    )
                    for root in roots
                )
            )
        )
        if roots
        else None
    )
    if subtree is None:
        return 0
    start = datetime.combine(job.window_start, time.min, tzinfo=UTC)
    end = datetime.combine(job.window_end + timedelta(days=1), time.min, tzinfo=UTC)
    candidates = select(RawEventSnapshot.id).where(
        RawEventSnapshot.programme_id == job.programme_id,
        RawEventSnapshot.mapping_version == job.mapping_version,
        RawEventSnapshot.source_connector == "tracker",
        RawEventSnapshot.program_uid.in_(program_uids),
        RawEventSnapshot.org_unit_id.in_(subtree),
        RawEventSnapshot.is_current.is_(True),
        RawEventSnapshot.extracted_at <= attempt_started,
        # The retrieval was bounded by occurredAt, not by death date. Null/outside dates
        # cannot be certified absent by this extraction, and must not be swept.
        RawEventSnapshot.occurred_at >= start,
        RawEventSnapshot.occurred_at < end,
    )
    withdrawn = 0
    last_id = None
    while True:
        page = candidates.order_by(RawEventSnapshot.id).limit(500)
        if last_id is not None:
            page = page.where(RawEventSnapshot.id > last_id)
        row_ids = session.scalars(page).all()
        if not row_ids:
            break
        # Finish each read cursor before updating, so drivers need not support
        # writes while a national-size streaming result remains open.
        last_id = row_ids[-1]
        batch = [row_id for row_id in row_ids if row_id not in seen_row_ids]
        if batch:
            session.execute(update(RawEventSnapshot).where(RawEventSnapshot.id.in_(batch)).values(is_current=False))
            withdrawn += len(batch)
    job.coverage_manifest = {**job.coverage_manifest, "withdrawn_event_count": withdrawn}
    record_operational_event(
        "event_withdrawals_reconciled", job_id=str(job.id), records_stored=withdrawn, session=session
    )
    return withdrawn

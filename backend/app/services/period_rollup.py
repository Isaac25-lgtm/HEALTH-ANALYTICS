"""Build any analysis period from stored months.

Months are the single stored source of truth for aggregate data. A financial year, quarter,
half-year, calendar year or custom month range is materialised as a real ``RawAggregateValue`` row
whose value is the sum of that unit's reported months, with the exact monthly rows it came from
recorded in its provenance. The calculation engine then reads it like any other row, and every
derived figure stays traceable to DHIS2.

Rules:

* A period is built only when **every** month in it has been extracted for the programme. A month
  that was never requested is unknown, not zero, so a year with a missing month stays unavailable.
* Within an extracted month, a unit that did not report contributes nothing - the same total DHIS2
  itself returns for the period. A unit with no reported month at all gets no row.
* Only summable mappings (SUM, COUNT) are rolled up. Other semantics stay unavailable rather than
  being summed incorrectly.
* When months are re-extracted, the derived row is rebuilt and the old one superseded. Older
  natively-extracted period rows are superseded too, so one current row per period remains and it
  always agrees with the months.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import Numeric, String, cast, func, select
from sqlalchemy.orm import Session

from app.domain.periods import PeriodError, parse_period
from app.integrations.dhis2.periods import months_in
from app.models import AnalyticsRevision, RawAggregateValue, RollupState, SourceMapping, SyncJob

DERIVATION = "sum_of_months"
_SUMMABLE = {"SUM", "COUNT"}
_ABSENT = {"no_source_row", "invalid_value"}


@dataclass
class RollupReport:
    periods: dict[str, dict] = field(default_factory=dict)

    def note(self, period: str, **values) -> None:
        self.periods.setdefault(period, {}).update(values)


def _aware(value: datetime | None) -> datetime | None:
    """SQLite returns naive timestamps; every comparison here is done in UTC."""
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _usable(row: RawAggregateValue) -> bool:
    return row.value is not None and not row.value_invalid and row.absence_reason not in _ABSENT


def _summable_keys(session: Session) -> set[tuple[UUID, str, str]]:
    rows = session.execute(
        select(
            SourceMapping.programme_id,
            SourceMapping.internal_source_key,
            SourceMapping.mapping_version,
            SourceMapping.aggregation_semantics,
            SourceMapping.item_kind,
            SourceMapping.enabled,
        )
    ).all()
    # A DHIS2 indicator is a ratio; summing its months is meaningless. A key currently bound to an
    # indicator is never summed; its longer periods are extracted natively instead (D-065).
    ratios = {
        (programme_id, key, version)
        for programme_id, key, version, _semantics, item_kind, enabled in rows
        if item_kind == "indicator"
    }
    return {
        (programme_id, key, version)
        for programme_id, key, version, semantics, _item_kind, _enabled in rows
        if str(semantics or "SUM").upper() in _SUMMABLE and (programme_id, key, version) not in ratios
    }


def _coverage_jobs(session: Session, months: tuple[str, ...]) -> list[SyncJob]:
    # A row in another district does not prove this key/geography was extracted. Old jobs
    # without a manifest cannot certify non-reporting; do not fabricate their history.
    return list(session.scalars(select(SyncJob).where(*_coverage_filter(months))).all())


def _missing_month_coverage(jobs, programme_id, unit_id, key, version, missing) -> list[SyncJob] | None:
    covered = set()
    used = []
    for job in jobs:
        manifest = job.coverage_manifest or {}
        if (
            job.programme_id != programme_id
            or job.mapping_version != version
            or not manifest.get("complete")
            or str(unit_id) not in manifest.get("org_unit_ids", [])
            or key not in manifest.get("source_keys", [])
        ):
            continue
        if "requests" in manifest:
            # New manifests distinguish direct percentages at parent units from
            # summable counts at peers. A union cannot prove both were requested.
            requested_periods = [
                period
                for request in manifest["requests"]
                if request.get("source_key") == key and str(unit_id) in request.get("org_unit_ids", [])
                for period in request.get("periods", [])
            ]
        else:
            requested_periods = (manifest.get("periods_by_source_key") or {}).get(key, manifest.get("periods", []))
        matching = set(requested_periods) & missing
        if matching:
            covered |= matching
            used.append(job)
    return used if missing <= covered else None


def _fingerprint(*columns):
    """Order-independent database fingerprint of a set of rows: the sum of a 64-bit hash of each."""
    text_value = func.concat_ws("|", *[func.coalesce(cast(column, String), "~") for column in columns])
    return cast(func.coalesce(func.sum(cast(func.hashtextextended(text_value, 0), Numeric)), 0), String)


def _coverage_filter(months: tuple[str, ...]) -> tuple:
    return (
        SyncJob.status == "succeeded",
        SyncJob.cancelled.is_(False),
        SyncJob.page_limit_reached.is_(False),
        SyncJob.rejected_count == 0,
        SyncJob.coverage_manifest.is_not(None),
        SyncJob.period_from <= months[-1],
        SyncJob.period_to >= months[0],
    )


def _unit_digests(session: Session, period: str, months: tuple[str, ...]) -> dict[str, str] | None:
    """A fingerprint of each unit's current rows for the period and its months; None off PostgreSQL.

    It covers everything a unit's roll-ups are built from and the roll-ups themselves, so a unit
    whose fingerprint is unchanged since it was verified need not be read again.
    """
    if session.get_bind().dialect.name != "postgresql":
        return None
    row = RawAggregateValue
    rows = session.execute(
        select(
            row.org_unit_id,
            func.count(row.id),
            _fingerprint(
                row.id,
                row.source_system,
                row.programme_id,
                row.internal_source_key,
                row.category_option_combo_uid,
                row.period,
                row.value,
                row.checksum,
                row.mapping_version,
                row.value_invalid,
                row.absence_reason,
            ),
        )
        .where(row.period.in_([*months, period]), row.is_current.is_(True))
        .group_by(row.org_unit_id)
    ).all()
    return {str(unit_id): f"{count}:{digest}" for unit_id, count, digest in rows}


def _job_digests(session: Session, months: tuple[str, ...]) -> dict[str, str]:
    rows = session.execute(
        select(
            SyncJob.id,
            _fingerprint(SyncJob.id, SyncJob.programme_id, SyncJob.mapping_version, SyncJob.coverage_manifest),
        )
        .where(*_coverage_filter(months))
        .group_by(SyncJob.id)
    ).all()
    return {str(job_id): digest for job_id, digest in rows}


def _units_certified_by(session: Session, job_ids: list[str]) -> set[str] | None:
    """Units whose non-reporting months a job can certify; None when a manifest does not say."""
    units: set[str] = set()
    for start in range(0, len(job_ids), 500):
        chunk = [UUID(value) for value in job_ids[start : start + 500]]
        for manifest in session.scalars(select(SyncJob.coverage_manifest).where(SyncJob.id.in_(chunk))):
            listed = (manifest or {}).get("org_unit_ids")
            if not isinstance(listed, list):
                return None
            units.update(str(value) for value in listed)
    return units


# Above this many changed units a scoped pass is no cheaper than reading the period once.
_SCOPED_REBUILD_LIMIT = 2000


def ensure_period_rollups(session: Session, periods: list[str]) -> RollupReport:
    """Materialise every non-month period in ``periods`` from its months, when they allow it.

    Compare each group's exact components, including invalidity and withdrawals. A global
    maximum timestamp cannot detect a deleted month or a change in another geography.

    Every input of a roll-up (source rows, mappings, coverage jobs) moves the global analytics
    revision when it changes, so a period verified at the present revision is not read again. When
    the revision has moved, PostgreSQL fingerprints each unit's rows: only units whose rows changed,
    or whose non-reporting months a new synchronisation can now certify, are verified again. A
    facility load for one district therefore costs one district, not the country. Revision and
    fingerprints are taken before any row is read, so a change committed during verification can
    only make the stored state older than what was verified, which forces the next call to look.
    """
    report = RollupReport()
    summable: set[tuple[UUID, str, str]] | None = None
    summable_digest: str | None = None
    revision = session.scalar(select(AnalyticsRevision.revision).where(AnalyticsRevision.key == "global"))
    for period in dict.fromkeys(periods):
        try:
            spec = parse_period(period)
        except PeriodError:
            continue
        if spec.kind == "month":
            continue
        tracked = revision is not None and len(spec.key) <= 40
        state = session.get(RollupState, spec.key) if tracked else None
        if state is not None and state.revision == revision:
            report.note(spec.key, status="current", created=0, superseded=0, skipped=0)
            continue
        months = months_in(spec)
        if summable is None:
            summable = _summable_keys(session)
            summable_digest = hashlib.sha256(
                repr(sorted((str(programme_id), key, version) for programme_id, key, version in summable)).encode()
            ).hexdigest()
        units_now = _unit_digests(session, spec.key, months) if tracked else None
        jobs_now = _job_digests(session, months) if units_now is not None else None
        scope: set[str] | None = None  # None: every unit
        if (
            units_now is not None
            and state is not None
            and state.units is not None
            and state.jobs is not None
            and state.summable_digest == summable_digest
            and not set(state.jobs) - set(jobs_now)
        ):
            changed = {
                unit for unit in set(units_now) | set(state.units) if units_now.get(unit) != state.units.get(unit)
            }
            changed_jobs = [job_id for job_id, digest in jobs_now.items() if state.jobs.get(job_id) != digest]
            certified = _units_certified_by(session, changed_jobs) if changed_jobs else set()
            if certified is not None and len(changed | certified) <= _SCOPED_REBUILD_LIMIT:
                scope = changed | certified
        if scope is not None and not scope:
            # The revision moved for rows this period does not read.
            state.revision = revision
            session.flush()
            report.note(spec.key, status="current", created=0, superseded=0, skipped=0)
            continue
        created, superseded, skipped = _rebuild_period(session, spec.key, months, summable, unit_ids=scope)
        if tracked:
            clean = not created and not superseded
            if state is None:
                state = RollupState(period=spec.key)
                session.add(state)
            verified = None
            if units_now is not None:
                verified = dict(units_now)
                if not clean:
                    # This pass changed rows itself; the units it touched are verified by the next.
                    if scope is None:
                        verified = {}
                    else:
                        for unit in scope:
                            verified.pop(unit, None)
            state.units = verified
            state.jobs = jobs_now
            state.summable_digest = summable_digest
            state.revision = revision if clean else None
            session.flush()
        report.note(
            spec.key,
            status="rebuilt" if created or superseded else "current",
            created=created,
            superseded=superseded,
            skipped=skipped,
        )
    return report


def _rebuild_period(
    session: Session,
    period: str,
    months: tuple[str, ...],
    summable: set[tuple[UUID, str, str]],
    unit_ids: set[str] | None = None,
) -> tuple[int, int, int]:
    """Bring the period's roll-ups up to date, for every unit or only for ``unit_ids``.

    A roll-up belongs to one unit and is built from that unit's rows alone, so a scoped pass is
    exact for the units it covers.
    """
    scope = [UUID(value) for value in unit_ids] if unit_ids is not None else None
    monthly_query = select(RawAggregateValue).where(
        RawAggregateValue.period.in_(months),
        RawAggregateValue.is_current.is_(True),
    )
    existing_query = select(RawAggregateValue).where(
        RawAggregateValue.period == period, RawAggregateValue.is_current.is_(True)
    )
    if scope is not None:
        monthly_query = monthly_query.where(RawAggregateValue.org_unit_id.in_(scope))
        existing_query = existing_query.where(RawAggregateValue.org_unit_id.in_(scope))
    monthly = session.scalars(monthly_query).all()
    groups: dict[tuple, list[RawAggregateValue]] = defaultdict(list)
    for row in monthly:
        groups[
            (
                row.source_system,
                row.programme_id,
                row.org_unit_id,
                row.internal_source_key,
                row.category_option_combo_uid,
            )
        ].append(row)

    existing = {
        (
            row.source_system,
            row.programme_id,
            row.org_unit_id,
            row.internal_source_key,
            row.category_option_combo_uid,
        ): row
        for row in session.scalars(existing_query).all()
    }

    coverage_jobs = _coverage_jobs(session, months)
    created = superseded = skipped = 0
    # Withdraw derived totals when all their components have been withdrawn.
    for key, previous in existing.items():
        if key not in groups and (previous.provenance or {}).get("derivation") == DERIVATION:
            previous.is_current = False
            superseded += 1
    for key, rows in groups.items():
        source_system, programme_id, org_unit_id, source_key, coc = key
        versions = {row.mapping_version for row in rows}
        previous = existing.get(key)
        if len(versions) != 1:
            if previous is not None and (previous.provenance or {}).get("derivation") == DERIVATION:
                previous.is_current = False
                superseded += 1
            skipped += 1
            continue
        version = next(iter(versions))
        if (programme_id, source_key, version) not in summable:
            if previous is not None and (previous.provenance or {}).get("derivation") == DERIVATION:
                previous.is_current = False
                superseded += 1
            skipped += 1
            continue
        missing = set(months) - {row.period for row in rows}
        coverage = _missing_month_coverage(coverage_jobs, programme_id, org_unit_id, source_key, version, missing)
        if missing and coverage is None:
            if previous is not None:
                previous.is_current = False
                superseded += 1
            skipped += 1
            continue
        invalid = any(not _usable(row) for row in rows)
        usable = sorted((row for row in rows if _usable(row)), key=lambda row: row.period)
        value = None if invalid else sum(float(row.value) for row in usable)
        ordered = sorted(rows, key=lambda row: (row.period, str(row.id)))
        component_ids = [str(row.id) for row in ordered]
        component_snapshot = [
            {
                "id": str(row.id),
                "period": row.period,
                "value": float(row.value) if row.value is not None else None,
                "checksum": row.checksum,
                "mapping_version": row.mapping_version,
                "value_invalid": row.value_invalid,
                "absence_reason": row.absence_reason,
            }
            for row in ordered
        ]
        checksum = hashlib.sha256(
            json.dumps([component_snapshot, sorted(str(job.id) for job in coverage or [])], sort_keys=True).encode(
                "utf-8"
            )
        ).hexdigest()

        if previous is not None and previous.checksum == checksum:
            continue
        if previous is not None:
            previous.is_current = False
            session.flush()
            superseded += 1

        template = ordered[0]
        derived = RawAggregateValue(
            id=uuid4(),
            source_system=source_system,
            programme_id=programme_id,
            org_unit_id=org_unit_id,
            period=period,
            source_metric_id=template.source_metric_id,
            internal_source_key=source_key,
            dhis2_org_unit_uid=template.dhis2_org_unit_uid,
            dhis2_item_uid=template.dhis2_item_uid,
            category_option_combo_uid=coc,
            value=value,
            extracted_at=max(_aware(row.extracted_at) for row in ordered),
            source_freshness_at=min(
                (_aware(row.source_freshness_at) for row in usable if row.source_freshness_at), default=None
            ),
            mapping_version=version,
            checksum=checksum,
            is_current=True,
            value_invalid=invalid,
            absence_reason="invalid_value" if invalid else None,
            provenance={
                "derivation": DERIVATION,
                "period": period,
                "months_requested": list(months),
                "months_reported": [row.period for row in usable],
                "component_row_ids": component_ids,
                "components": component_snapshot,
                "non_reporting_months": sorted(missing),
                "coverage_job_ids": [str(job.id) for job in coverage or []],
                "mapping_version": version,
            },
        )
        session.add(derived)
        session.flush()
        if previous is not None:
            previous.superseded_by_id = derived.id
        created += 1
    session.flush()
    return created, superseded, skipped

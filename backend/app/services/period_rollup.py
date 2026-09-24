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

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.periods import PeriodError, parse_period
from app.integrations.dhis2.periods import months_in
from app.models import RawAggregateValue, SourceMapping

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
        )
    ).all()
    return {
        (programme_id, key, version)
        for programme_id, key, version, semantics in rows
        if str(semantics or "SUM").upper() in _SUMMABLE
    }


def _extracted_months(session: Session, months: tuple[str, ...]) -> dict[UUID, set[str]]:
    """Months that hold at least one current row, per programme, anywhere in the country."""
    found: dict[UUID, set[str]] = defaultdict(set)
    for programme_id, period in session.execute(
        select(RawAggregateValue.programme_id, RawAggregateValue.period)
        .where(RawAggregateValue.period.in_(months), RawAggregateValue.is_current.is_(True))
        .distinct()
    ).all():
        found[programme_id].add(period)
    return found


def _latest_month_extraction(session: Session, months: tuple[str, ...]) -> datetime | None:
    return _aware(
        session.scalar(
            select(func.max(RawAggregateValue.extracted_at)).where(
                RawAggregateValue.period.in_(months), RawAggregateValue.is_current.is_(True)
            )
        )
    )


def _latest_derivation(session: Session, period: str) -> datetime | None:
    latest = session.scalar(
        select(func.max(RawAggregateValue.extracted_at)).where(
            RawAggregateValue.period == period,
            RawAggregateValue.is_current.is_(True),
            RawAggregateValue.provenance["derivation"].as_string() == DERIVATION,
        )
    )
    return _aware(latest) if latest is not None else None


def ensure_period_rollups(session: Session, periods: list[str]) -> RollupReport:
    """Materialise every non-month period in ``periods`` from its months, when they allow it.

    Cheap when nothing changed: a period is rebuilt only if its months were extracted after the
    last derivation, so ordinary dashboard loads do no aggregation work.
    """
    report = RollupReport()
    summable: set[tuple[UUID, str, str]] | None = None
    for period in dict.fromkeys(periods):
        try:
            spec = parse_period(period)
        except PeriodError:
            continue
        if spec.kind == "month":
            continue
        months = months_in(spec)
        latest_month = _latest_month_extraction(session, months)
        if latest_month is None:
            report.note(spec.key, status="no_monthly_data")
            continue
        latest_derived = _latest_derivation(session, spec.key)
        if latest_derived is not None and latest_derived >= latest_month:
            report.note(spec.key, status="current")
            continue
        if summable is None:
            summable = _summable_keys(session)
        created, superseded, skipped = _rebuild_period(session, spec.key, months, summable)
        report.note(spec.key, status="rebuilt", created=created, superseded=superseded, skipped=skipped)
    return report


def _rebuild_period(
    session: Session,
    period: str,
    months: tuple[str, ...],
    summable: set[tuple[UUID, str, str]],
) -> tuple[int, int, int]:
    extracted = _extracted_months(session, months)
    complete_programmes = {pid for pid, have in extracted.items() if set(months) <= have}
    if not complete_programmes:
        # No programme has every month of this period, so nothing can be built honestly.
        return 0, 0, 0

    monthly = session.scalars(
        select(RawAggregateValue).where(
            RawAggregateValue.period.in_(months),
            RawAggregateValue.is_current.is_(True),
            RawAggregateValue.programme_id.in_(complete_programmes),
        )
    ).all()
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
        for row in session.scalars(
            select(RawAggregateValue).where(
                RawAggregateValue.period == period, RawAggregateValue.is_current.is_(True)
            )
        ).all()
    }

    created = superseded = skipped = 0
    for key, rows in groups.items():
        source_system, programme_id, org_unit_id, source_key, coc = key
        versions = {row.mapping_version for row in rows}
        if len(versions) != 1:
            skipped += 1
            continue
        version = next(iter(versions))
        if (programme_id, source_key, version) not in summable:
            skipped += 1
            continue
        usable = sorted((row for row in rows if _usable(row)), key=lambda row: row.period)
        if not usable:
            continue
        value = sum(float(row.value) for row in usable)
        component_ids = [str(row.id) for row in usable]
        checksum = hashlib.sha256(
            json.dumps([[row.period, str(row.id), float(row.value)] for row in usable]).encode("utf-8")
        ).hexdigest()

        previous = existing.get(key)
        if previous is not None and previous.checksum == checksum:
            continue
        if previous is not None:
            previous.is_current = False
            session.flush()
            superseded += 1

        template = usable[0]
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
            extracted_at=max(_aware(row.extracted_at) for row in usable),
            source_freshness_at=min(
                (_aware(row.source_freshness_at) for row in usable if row.source_freshness_at), default=None
            ),
            mapping_version=version,
            checksum=checksum,
            is_current=True,
            value_invalid=False,
            provenance={
                "derivation": DERIVATION,
                "period": period,
                "months_requested": list(months),
                "months_reported": [row.period for row in usable],
                "component_row_ids": component_ids,
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

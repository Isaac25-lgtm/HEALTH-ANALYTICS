"""Read prepared, private snapshots without recalculating on every navigation.

Source/configuration writes invalidate products transactionally through database triggers.
The revision is deliberately global for now: over-invalidation is safe; stale reuse is not.
No identifiable data or passwords are introduced by this cache.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path

from sqlalchemy import func, select

from app.config import get_settings
from app.domain.modules import MODULE_PROGRAMME
from app.models import AnalysisSnapshot, AnalyticsRevision, RawEventSnapshot, SyncJob
from app.services.analysis import load_snapshot, request_matches, snapshot_response
from app.services.authorization import programme_scope_codes, user_actions


@lru_cache(maxsize=1)
def calculation_build_signature() -> str:
    root = Path(__file__).resolve().parents[1]
    files = (
        "services/calculation.py",
        "services/period_rollup.py",
        "services/population.py",
        "services/classification.py",
        "services/modules.py",
        "services/dashboard.py",
        "services/geometry.py",
        "services/mpdsr_events.py",
        "services/event_coverage.py",
        "services/mpdsr.py",
        "services/quality.py",
        "services/geography.py",
        "services/authorization.py",
        "services/facility_data.py",
        "services/analysis.py",
        "services/prepared_dashboard.py",
        "domain/formula_spec.py",
        "domain/indicator_catalog.py",
        "domain/periods.py",
        "domain/modules.py",
        "domain/mpdsr_cause_taxonomy.py",
    )
    digest = hashlib.sha256()
    for file in files:
        digest.update(file.encode())
        digest.update((root / file).read_bytes())
    return digest.hexdigest()


def prepared_signature(session, user, *, revision: int | None = None) -> str | None:
    if revision is None:
        revision = session.scalar(select(AnalyticsRevision.revision).where(AnalyticsRevision.key == "global"))
    if revision is None:
        return None
    settings = get_settings()
    material = {
        "revision": revision,
        "build": calculation_build_signature(),
        "actions": sorted(user_actions(session, user)),
        "programmes": sorted(programme_scope_codes(session, user)),
        "undated_policy": settings.undated_formula_policy,
        "cause_minimum": settings.mpdsr_cause_min_cell_count,
        "mpdsr_reporting_approved": settings.mpdsr_reporting_units_approved,
        "event_retention_hours": settings.mpdsr_event_retention_hours,
        "freshness_hours": settings.dhis2_stale_hours,
    }
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()


def preparation_metadata(session, user, module: str) -> dict:
    # Flush material writes before capturing their revision; never capture a pre-write token.
    session.flush()
    now = datetime.now(UTC)
    expiry = now + timedelta(hours=6)
    if MODULE_PROGRAMME.get(module) == "MPDSR":
        settings = get_settings()
        retention = timedelta(hours=settings.mpdsr_event_retention_hours)
        oldest = session.scalar(
            select(func.min(RawEventSnapshot.extracted_at)).where(
                RawEventSnapshot.is_current.is_(True),
                RawEventSnapshot.extracted_at > now - retention,
            )
        )
        if oldest is not None:
            expiry = min(expiry, _utc(oldest) + retention)
        freshness = timedelta(hours=min(settings.dhis2_stale_hours, settings.mpdsr_event_retention_hours))
        oldest_job = session.scalar(
            select(func.min(SyncJob.finished_at)).where(
                SyncJob.job_type == "tracker",
                SyncJob.status == "succeeded",
                SyncJob.finished_at > now - freshness,
            )
        )
        if oldest_job is not None:
            expiry = min(expiry, _utc(oldest_job) + freshness)
        # A zero for the ongoing cohort can change at midnight as its required extraction
        # end advances. Do not keep yesterday's verified coverage until the six-hour TTL.
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        expiry = min(expiry, tomorrow)
    current = session.scalar(select(AnalyticsRevision.revision).where(AnalyticsRevision.key == "global"))
    captured = session.info.get("product_input_revision")
    # Sign the inputs we actually read, never a second revision fetched after this guard.
    signature = (
        prepared_signature(session, user, revision=captured) if captured is not None and captured == current else None
    )
    return {
        "signature": signature,
        "valid_until": expiry.isoformat(),
        "input_revision": captured,
        "revision_changed_during_preparation": captured != current,
    }


def _utc(moment):
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def find_prepared_dashboard(
    session, user, *, org_unit_id, period, module=None, comparison_period=None, selected_indicator=None
) -> dict | None:
    if module is None:
        from app.services.dashboard import default_module

        module = default_module(programme_scope_codes(session, user))
    signature = prepared_signature(session, user)
    if signature is None:
        return None
    query = select(AnalysisSnapshot).where(
        AnalysisSnapshot.user_id == user.id,
        AnalysisSnapshot.org_unit_id == org_unit_id,
        AnalysisSnapshot.period == period,
        AnalysisSnapshot.status == "succeeded",
        AnalysisSnapshot.view_config["preparation"]["signature"].as_string() == signature,
    )
    if module:
        query = query.where(AnalysisSnapshot.module == module)
    now = datetime.now(UTC)
    # Query only the latest matching request rather than deserialize an unbounded history.
    query = (
        query.where(
            AnalysisSnapshot.view_config["request"]["comparison_period"].as_string() == comparison_period,
            AnalysisSnapshot.view_config["request"]["selected_indicator"].as_string() == selected_indicator,
        )
        .order_by(AnalysisSnapshot.created_at.desc(), AnalysisSnapshot.id.desc())
        .limit(1)
    )
    row = session.scalar(query)
    if row is None or not request_matches(
        row,
        org_unit_id=org_unit_id,
        period=period,
        module=module,
        comparison_period=comparison_period,
        selected_indicator=selected_indicator,
    ):
        return None
    until = (row.view_config.get("preparation") or {}).get("valid_until")
    if not until or _utc(datetime.fromisoformat(until)) <= now:
        return None
    # Creator, current geography, programme and action are checked again on every read.
    return snapshot_response(load_snapshot(session, user=user, snapshot_id=row.id), reused=True)

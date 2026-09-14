from __future__ import annotations

import hashlib
import json
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import ActionPermission, JobStatus
from app.domain.modules import MODULE_PROGRAMME
from app.models import AnalysisSnapshot, User
from app.services.authorization import (
    AuthorizationError,
    require_action,
    require_org_unit_access,
    require_programme_access,
)
from app.version import SOFTWARE_VERSION


def compute_view_hash(
    *,
    org_unit_id: UUID | str,
    period: str,
    comparison_period: str | None,
    module: str,
    selected_indicator: str | None,
) -> str:
    payload = {
        "org_unit_id": str(org_unit_id),
        "period": period,
        "comparison_period": comparison_period,
        "module": module,
        "selected_indicator": selected_indicator,
        "software_version": SOFTWARE_VERSION,
    }
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def find_request_snapshot(session: Session, *, user: User, request_key: str) -> AnalysisSnapshot | None:
    return session.scalar(
        select(AnalysisSnapshot).where(
            AnalysisSnapshot.user_id == user.id,
            AnalysisSnapshot.idempotency_key == request_key,
            AnalysisSnapshot.status == JobStatus.SUCCEEDED.value,
        )
    )


def request_matches(
    row: AnalysisSnapshot,
    *,
    org_unit_id: UUID,
    period: str,
    module: str | None,
    comparison_period: str | None,
    selected_indicator: str | None,
) -> bool:
    """A reused request key must describe the same analytical request."""
    config = row.view_config or {}
    requested = config.get("request") or {}
    return (
        str(row.org_unit_id) == str(org_unit_id)
        and row.period == period
        and (module is None or row.module == module)
        and requested.get("comparison_period") == comparison_period
        and requested.get("selected_indicator") == selected_indicator
    )


def persist_snapshot(
    session: Session,
    *,
    user: User,
    dashboard: dict,
    evidence: dict,
    request_key: str | None = None,
    request: dict | None = None,
) -> AnalysisSnapshot:
    snapshot_id = uuid4()
    view_hash = compute_view_hash(
        org_unit_id=dashboard["scope"]["id"],
        period=dashboard["period"],
        comparison_period=dashboard.get("comparison_period"),
        module=dashboard["module"],
        selected_indicator=dashboard.get("ranking", {}).get("indicator_code"),
    )
    run_id = dashboard.get("module_result", {}).get("current_run_id")
    # Identifiers are written into the payload before the row is stored, so the committed
    # snapshot is exactly what the client receives.
    dashboard["analysis_snapshot_id"] = str(snapshot_id)
    dashboard["view_hash"] = view_hash
    dashboard["request_key"] = request_key
    evidence["analysis_snapshot_id"] = str(snapshot_id)
    evidence["view_hash"] = view_hash
    evidence["current_run_id"] = evidence.get("current_run_id") or (str(run_id) if run_id else None)
    row = AnalysisSnapshot(
        id=snapshot_id,
        user_id=user.id,
        org_unit_id=UUID(str(dashboard["scope"]["id"])),
        period=dashboard["period"],
        comparison_period=dashboard.get("comparison_period"),
        module=dashboard["module"],
        selected_indicator=dashboard.get("ranking", {}).get("indicator_code"),
        view_hash=view_hash,
        current_run_id=UUID(str(run_id)) if run_id else None,
        status=JobStatus.SUCCEEDED.value,
        software_version=SOFTWARE_VERSION,
        payload_json=dashboard,
        evidence_json=evidence,
        idempotency_key=request_key,
        view_config={
            "org_unit_code": dashboard.get("scope", {}).get("code"),
            "period": dashboard["period"],
            "comparison_period": dashboard.get("comparison_period"),
            "module": dashboard["module"],
            "selected_indicator": dashboard.get("ranking", {}).get("indicator_code"),
            "request": request or {},
        },
    )
    session.add(row)
    session.flush()
    return row


def _authorise_snapshot(session: Session, user: User, row: AnalysisSnapshot) -> None:
    """Snapshots are private to their creator and re-checked against current permissions."""
    if row.user_id != user.id:
        raise AuthorizationError("not_found", "Analytical snapshot was not found.")
    require_action(session, user, ActionPermission.VIEW)
    require_org_unit_access(session, user, row.org_unit_id)
    programme = MODULE_PROGRAMME.get(row.module)
    if programme is None:
        raise AuthorizationError("not_found", "Analytical snapshot was not found.")
    require_programme_access(session, user, programme)


def load_snapshot(
    session: Session,
    *,
    user: User,
    snapshot_id: UUID,
    org_unit_id: UUID | None = None,
    period: str | None = None,
    module: str | None = None,
    comparison_period: str | None = None,
    view_hash: str | None = None,
) -> AnalysisSnapshot:
    row = session.get(AnalysisSnapshot, snapshot_id)
    if row is None or row.status != JobStatus.SUCCEEDED.value:
        raise AuthorizationError("not_found", "Analytical snapshot was not found.")
    _authorise_snapshot(session, user, row)
    if org_unit_id and row.org_unit_id != org_unit_id:
        raise AuthorizationError("snapshot_mismatch", "Geography does not match the analytical snapshot.")
    if period and row.period != period:
        raise AuthorizationError("snapshot_mismatch", "Period does not match the analytical snapshot.")
    if module and row.module != module:
        raise AuthorizationError("snapshot_mismatch", "Module does not match the analytical snapshot.")
    if comparison_period and row.comparison_period and row.comparison_period != comparison_period:
        raise AuthorizationError("snapshot_mismatch", "Comparison period does not match the analytical snapshot.")
    if view_hash and row.view_hash != view_hash:
        raise AuthorizationError("snapshot_conflict", "View configuration hash does not match the snapshot.")
    return row


def snapshot_response(row: AnalysisSnapshot, *, reused: bool = False) -> dict:
    payload = dict(row.payload_json or {})
    payload["analysis_snapshot_id"] = str(row.id)
    payload["view_hash"] = row.view_hash
    payload["request_key"] = row.idempotency_key
    payload["snapshot_reused"] = reused
    payload["snapshot_created_at"] = row.created_at.isoformat() if row.created_at else None
    return payload

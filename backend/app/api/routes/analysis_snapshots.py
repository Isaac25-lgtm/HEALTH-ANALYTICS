from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, parse_uuid, raise_authz
from app.db.session import get_db
from app.models import User
from app.services.analysis import load_snapshot, snapshot_response
from app.services.authorization import AuthorizationError
from app.services.geometry import snapshot_map_features

router = APIRouter(prefix="/analysis-snapshots", tags=["analysis-snapshots"])


@router.get("/{snapshot_id}")
def get_snapshot(
    snapshot_id: str,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Return an already committed snapshot. Read-only; creates no records."""
    try:
        row = load_snapshot(session, user=user, snapshot_id=parse_uuid(snapshot_id, "snapshot_id"))
    except AuthorizationError as error:
        raise_authz(error)
    return snapshot_response(row)


@router.get("/{snapshot_id}/map-features")
def get_snapshot_map_features(
    snapshot_id: str,
    simplify: bool = True,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> JSONResponse:
    """Features for exactly the snapshot's map cohort, valued from the snapshot. Read-only."""
    try:
        row = load_snapshot(session, user=user, snapshot_id=parse_uuid(snapshot_id, "snapshot_id"))
    except AuthorizationError as error:
        raise_authz(error)
    payload = row.payload_json or {}
    map_block = payload.get("map") or {}
    if not map_block.get("geometry_effective_date"):
        return JSONResponse(
            content={
                "type": "FeatureCollection",
                "map_state": "not_available",
                "mapping_note": "This snapshot predates the map cohort contract.",
                "features": [],
                "feature_count": 0,
            }
        )
    module_result = payload.get("module_result") or {}
    if payload.get("screen") == "facility":
        value_rows = [
            {
                "org_unit_id": payload.get("scope", {}).get("id"),
                "calculation_run_id": module_result.get("current_run_id"),
                "values": {
                    item.get("indicator_code"): item
                    for item in module_result.get("indicators") or []
                    if item.get("indicator_code")
                },
            }
        ]
    else:
        value_rows = module_result.get("org_unit_comparison") or []
    content = snapshot_map_features(session, user, map_block=map_block, value_rows=value_rows, simplify=simplify)
    return JSONResponse(content=content, headers={"Cache-Control": "private, max-age=3600", "Vary": "Cookie"})

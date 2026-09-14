from uuid import UUID

from sqlalchemy.orm import Session

from app.models import AuditLog, OrgUnit


def write_audit(
    session: Session,
    *,
    actor_user_id: UUID | None,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    before: dict | None = None,
    after: dict | None = None,
    reason: str | None = None,
    ip_address: str | None = None,
    commit: bool = False,
) -> AuditLog:
    # Never persist secret material in audit payloads.
    redacted_before = _redact(before)
    redacted_after = _redact(after)
    entry = AuditLog(
        actor_user_id=actor_user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        before_json=redacted_before,
        after_json=redacted_after,
        reason=reason,
        ip_address=ip_address,
    )
    session.add(entry)
    session.flush()
    if commit:
        session.commit()
        session.refresh(entry)
    return entry


_SECRET_KEYS = {"password", "password_hash", "token", "api_key", "secret", "data_values"}


def _redact(payload: dict | None) -> dict | None:
    if payload is None:
        return None
    clean: dict = {}
    for key, value in payload.items():
        if key.lower() in _SECRET_KEYS:
            clean[key] = "[redacted]"
        else:
            clean[key] = value
    return clean


def org_unit_payload(org_unit: OrgUnit) -> dict:
    return {
        "id": str(org_unit.id),
        "code": org_unit.code,
        "name": org_unit.name,
        "level_type": org_unit.level_type,
        "path": org_unit.path,
    }

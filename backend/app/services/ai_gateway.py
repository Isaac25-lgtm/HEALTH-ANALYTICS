from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain.enums import ActionPermission, ChangeInterpretation, JobStatus, PrivacyClass
from app.domain.modules import MODULE_PROGRAMME
from app.integrations.ai.providers import resolve_provider
from app.models import AiRequest, User
from app.services.analysis import load_snapshot
from app.services.authorization import (
    AuthorizationError,
    require_action,
    require_org_unit_access,
    require_programme_access,
)
from app.services.evidence import (
    blame_or_causation_matches,
    contains_unsupported_number,
    evidence_hash,
    evidence_package,
    question_is_unsupported,
    validate_statements,
)
from app.services.rate_limit import check_rate

PROMPT_VERSION = "hpip-ai-2"

RESPONSE_SCHEMA = {
    "name": "hpip.statements.v1",
    "type": "object",
    "required": ["statements"],
    "properties": {
        "statements": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["text", "kind", "evidence_refs"],
                "properties": {
                    "text": {"type": "string"},
                    "kind": {
                        "enum": [
                            "observation",
                            "association",
                            "data_quality",
                            "insufficient_evidence",
                            "recommendation",
                        ]
                    },
                    "evidence_refs": {"type": "array", "items": {"type": "string"}},
                },
            },
        }
    },
}


def _change_detail(row: dict) -> str:
    change = row.get("change") or {}
    if change.get("percentage_point_change") is not None:
        return f"{change['percentage_point_change']:+.1f} percentage points"
    if change.get("absolute_change") is not None:
        return f"{change['absolute_change']:+.1f} {row.get('unit') or ''}".strip()
    return "no comparable change"


def _findings(package: dict) -> list[dict]:
    """Deterministic, direction-aware findings. Never calls a BLUE or unclassified change improvement."""
    findings = []
    for row in package.get("indicators") or []:
        name = row.get("name") or row.get("indicator_code")
        run_id = row.get("calculation_run_id")
        interpretation = (row.get("change") or {}).get("interpretation") or row.get("interpretation")
        if row.get("raw_value") is None:
            findings.append(
                {
                    "title": f"{name} has no verified value",
                    "detail": row.get("blue_reason") or "A required component is missing.",
                    "indicator_code": row.get("indicator_code"),
                    "evidence_run_id": run_id,
                    "kind": "data_quality",
                }
            )
            continue
        if row.get("quality_status") == "blue" or row.get("status") == "blue":
            findings.append(
                {
                    "title": f"{name} is non-assessable",
                    "detail": row.get("blue_reason") or "BLUE is a data-quality state, not high performance.",
                    "indicator_code": row.get("indicator_code"),
                    "evidence_run_id": run_id,
                    "kind": "data_quality",
                }
            )
            continue
        if row.get("status") == "red":
            findings.append(
                {
                    "title": f"{name} is outside the approved performance band",
                    "detail": (
                        f"Verified value {row.get('display_value') or row.get('raw_value')} "
                        f"{row.get('unit') or ''} from calculation run {run_id}."
                    ),
                    "indicator_code": row.get("indicator_code"),
                    "evidence_run_id": run_id,
                    "kind": "observation",
                }
            )
        if interpretation == ChangeInterpretation.IMPROVED.value:
            findings.append(
                {
                    "title": f"{name} improved against the comparison period",
                    "detail": f"Verified change {_change_detail(row)} from calculation run {run_id}.",
                    "indicator_code": row.get("indicator_code"),
                    "evidence_run_id": run_id,
                    "kind": "observation",
                }
            )
        elif interpretation == ChangeInterpretation.DETERIORATED.value:
            findings.append(
                {
                    "title": f"{name} deteriorated against the comparison period",
                    "detail": f"Verified change {_change_detail(row)} from calculation run {run_id}.",
                    "indicator_code": row.get("indicator_code"),
                    "evidence_run_id": run_id,
                    "kind": "observation",
                }
            )
    if not findings:
        findings.append(
            {
                "title": "No priority exceptions in the verified evidence",
                "detail": (
                    "Available indicators were calculated. No red, BLUE or interpretable deteriorations were present."
                ),
                "indicator_code": None,
                "evidence_run_id": package.get("current_run_id"),
                "kind": "insufficient_evidence",
            }
        )
    return findings[:3]


def _explain(package: dict, indicator_code: str | None) -> dict:
    row = next(
        (item for item in package.get("indicators") or [] if item.get("indicator_code") == indicator_code),
        None,
    )
    if row is None:
        return {
            "unsupported": True,
            "text": "That indicator is not in the authorised verified evidence package.",
        }
    interpretation = row.get("interpretation") or "not_interpreted"
    return {
        "unsupported": False,
        "text": (
            f"{row.get('name')} is {row.get('display_value') or 'unavailable'} "
            f"{row.get('unit') or ''} with status {row.get('status')}. "
            f"Numerator {row.get('numerator')}; denominator {row.get('denominator')}. "
            f"Change interpretation: {interpretation.replace('_', ' ')}. "
            f"{row.get('blue_reason') or 'This explanation uses only the calculation run evidence.'}"
        ),
        "indicator_code": indicator_code,
        "evidence_run_id": row.get("calculation_run_id"),
    }


def _ask(package: dict, question: str) -> dict:
    if question_is_unsupported(question):
        return {
            "unsupported": True,
            "text": (
                "This question asks for fault-finding or causal attribution, which the verified evidence cannot "
                "support. Routine indicators and review categories can show associations and documented "
                "categories only."
            ),
        }
    lowered = (question or "").lower()
    for row in package.get("indicators") or []:
        code = (row.get("indicator_code") or "").lower()
        name = (row.get("name") or "").lower()
        if (code and code in lowered) or (name and name in lowered):
            return _explain(package, row.get("indicator_code"))
    if "red" in lowered:
        reds = [row.get("name") for row in package.get("indicators") or [] if row.get("status") == "red"]
        return {
            "unsupported": False,
            "text": (
                "Verified off-track indicators: " + ", ".join(reds)
                if reds
                else "No verified indicator in this package has a red status."
            ),
            "evidence_run_id": package.get("current_run_id"),
        }
    return {
        "unsupported": True,
        "text": "The question is not answered because it is not grounded in the authorised evidence package.",
    }


def _provider_complete(package: dict, task: str, question: str | None) -> tuple[dict | None, str | None]:
    settings = get_settings()
    if not (settings.ai_enabled and settings.ai_api_key and settings.ai_base_url):
        return None, None
    if not settings.ai_base_url.startswith("https://"):
        return None, "insecure_ai_endpoint"
    payload = {
        "model": settings.ai_model or "unspecified",
        "task": task,
        "prompt_version": settings.ai_prompt_version or PROMPT_VERSION,
        "evidence": package,
        "question": question,
        "max_tokens": settings.ai_max_tokens,
        "response_schema": RESPONSE_SCHEMA,
        "constraints": [
            "Use only facts in the evidence object.",
            "Every statement must cite indicator codes from the evidence in evidence_refs.",
            "Describe associations as associations. Never state or imply blame, negligence or causation.",
            "If the evidence cannot answer, return one insufficient_evidence statement.",
        ],
    }
    try:
        completion = resolve_provider(
            settings.ai_provider,
            base_url=settings.ai_base_url,
            api_key=settings.ai_api_key,
        ).complete(payload, timeout=settings.ai_timeout_seconds)
    except Exception:
        return None, "provider_failed"
    if completion.error_code:
        return None, completion.error_code
    if completion.statements is not None:
        statements, error = validate_statements(completion.statements, package)
        if error:
            return None, error
        text = " ".join(item["text"] for item in statements)
    else:
        statements = None
        text = completion.text
        if not text:
            return None, "empty_response"
        if blame_or_causation_matches(text):
            return None, "unsafe_causal_or_blame_language"
        if contains_unsupported_number(text, package):
            return None, "unsupported_numeric_claim"
    return {
        "text": text,
        "statements": statements,
        "provider": completion.provider,
        "model": completion.model,
        "token_usage": completion.token_usage,
    }, None


def run_ai_task(
    session: Session,
    *,
    user: User,
    org_unit_id: UUID,
    period: str,
    module: str | None,
    task: str,
    question: str | None = None,
    indicator_code: str | None = None,
    comparison_period: str | None = None,
    analysis_snapshot_id: UUID | None = None,
    view_hash: str | None = None,
) -> dict:
    require_action(session, user, ActionPermission.VIEW)
    require_org_unit_access(session, user, org_unit_id)
    if module:
        if module not in MODULE_PROGRAMME:
            raise AuthorizationError("invalid_input", "Analytical module is not recognised.")
        require_programme_access(session, user, MODULE_PROGRAMME[module])
    if task in {"report", "brief"}:
        require_action(session, user, ActionPermission.GENERATE_AI_REPORT)
    if analysis_snapshot_id is None:
        raise AuthorizationError(
            "snapshot_required",
            "AI must consume the displayed analytical snapshot. Recalculation is not permitted.",
        )
    check_rate(user.id, f"ai:{task}", limit=get_settings().ai_rate_limit)
    # load_snapshot enforces ownership plus the snapshot's own programme, so omitting
    # ``module`` can never widen access.
    snapshot = load_snapshot(
        session,
        user=user,
        snapshot_id=analysis_snapshot_id,
        org_unit_id=org_unit_id,
        period=period,
        module=module,
        comparison_period=comparison_period,
        view_hash=view_hash,
    )
    dashboard = snapshot.payload_json or {}
    package = snapshot.evidence_json or evidence_package(dashboard)
    # The size limit bounds what may leave the platform. Deterministic answers stay local,
    # so an oversized package skips the external provider instead of blocking the user.
    oversized = len(str(package)) > get_settings().ai_max_evidence_chars
    if task == "findings":
        fallback = {"findings": _findings(package), "mode": "deterministic"}
    elif task == "explain":
        fallback = {**_explain(package, indicator_code), "mode": "deterministic"}
    elif task == "ask":
        fallback = {**_ask(package, question or ""), "mode": "deterministic"}
    elif task in {"report", "brief"}:
        fallback = {
            "text": " ".join(item["detail"] for item in _findings(package)),
            "mode": "deterministic",
            "unsupported": False,
        }
    else:
        raise AuthorizationError("invalid_input", "Unsupported AI task.")

    provider_error = None
    if task == "ask" and question_is_unsupported(question or ""):
        provider, provider_error = None, "unsafe_causal_or_blame_question"
    elif dashboard.get("module") == "mpdsr" and get_settings().ai_enabled:
        provider, provider_error = None, "restricted_mpdsr_external_blocked"
    elif oversized and get_settings().ai_enabled:
        provider, provider_error = None, "evidence_exceeds_provider_limit"
    else:
        provider, provider_error = _provider_complete(package, task, question)
    used_fallback = provider is None
    result = fallback if used_fallback else {**fallback, **provider, "mode": "provider", "fallback_used": False}
    if used_fallback:
        result["fallback_used"] = True
        result["mode"] = "deterministic"

    run_id = (dashboard.get("module_result") or {}).get("current_run_id") or snapshot.current_run_id
    record = AiRequest(
        id=uuid4(),
        user_id=user.id,
        task=task,
        provider=result.get("provider") if not used_fallback else None,
        model=result.get("model") if not used_fallback else None,
        evidence_hash=evidence_hash(package),
        calculation_run_id=UUID(str(run_id)) if run_id else None,
        analysis_snapshot_id=snapshot.id,
        sensitivity_class=(
            PrivacyClass.PUBLIC_AGGREGATE.value
            if dashboard.get("module") != "mpdsr"
            else PrivacyClass.RESTRICTED_EVENT.value
        ),
        token_usage=result.get("token_usage"),
        status=JobStatus.SUCCEEDED.value,
        prompt_version=get_settings().ai_prompt_version or PROMPT_VERSION,
        fallback_used=used_fallback,
        error_code=provider_error,
        response_json={
            "task": task,
            "unsupported": result.get("unsupported", False),
            "mode": result.get("mode"),
            "text": result.get("text"),
            "findings": result.get("findings"),
            "statements": result.get("statements"),
        },
    )
    session.add(record)
    session.flush()
    return {
        "ai_request_id": str(record.id),
        "task": task,
        "mode": result["mode"],
        "fallback_used": used_fallback,
        "prompt_version": record.prompt_version,
        "evidence_hash": record.evidence_hash,
        "calculation_run_id": str(record.calculation_run_id) if record.calculation_run_id else None,
        "analysis_snapshot_id": str(snapshot.id),
        "generated_at": datetime.now(UTC).isoformat(),
        "result": result,
    }

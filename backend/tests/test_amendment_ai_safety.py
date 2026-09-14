"""Amendment §11: blame and unsupported causation are refused; provider output is schema-validated."""

from uuid import UUID

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.models import AiRequest, OrgUnit
from app.services.evidence import blame_or_causation_matches, validate_statements
from tests.conftest import auth_header, login, query_dashboard
from tests.helpers import put_population, put_raw

BLAME_PHRASES = [
    "Was this negligence?",
    "Were the midwives negligent?",
    "Which facility should be blamed?",
    "Who is to blame for these outcomes?",
    "How many preventable deaths happened here?",
    "Was this a preventable death?",
    "Were these deaths caused by staff?",
    "Is this a staff failure?",
    "Is this a facility failure?",
    "Has poor care caused these deaths?",
    "Who is responsible for death at Pader HC III?",
]

SAFE_TEXT = [
    "Districts with lower ANC4 coverage were associated with higher perinatal mortality in this period.",
    "The review documented obstetric haemorrhage as a structured cause category.",
    "Institutional delivery coverage decreased by 3.8 percentage points.",
]


@pytest.mark.parametrize("phrase", BLAME_PHRASES)
def test_blame_and_causation_phrases_are_detected(phrase):
    assert blame_or_causation_matches(phrase)


@pytest.mark.parametrize("text", SAFE_TEXT)
def test_association_wording_is_not_flagged(text):
    assert blame_or_causation_matches(text) == []


def _snapshot(client, session):
    pader = session.scalar(select(OrgUnit).where(OrgUnit.code == "PADER"))
    put_population(session, pader, 2024, 1_000_000, code="SAFETY_POP")
    put_raw(session, pader, "FY2024/25", "ANC1", 40_000)
    put_raw(session, pader, "FY2024/25", "ANC4", 20_000)
    session.commit()
    headers = auth_header(login(client, "pader.focal"))
    dash = query_dashboard(client, headers, pader.id)
    assert dash.status_code == 201, dash.text
    body = dash.json()
    request = {
        "org_unit_id": str(pader.id),
        "period": "FY2024/25",
        "module": "anc",
        "analysis_snapshot_id": body["analysis_snapshot_id"],
        "view_hash": body["view_hash"],
    }
    return headers, request, body


@pytest.mark.parametrize("phrase", BLAME_PHRASES)
def test_blame_questions_are_refused_through_the_api(client, session, phrase):
    headers, request, _ = _snapshot(client, session)
    response = client.post("/ai/ask", json={**request, "question": phrase}, headers=headers)
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["unsupported"] is True
    assert blame_or_causation_matches(result["text"]) == []
    record = session.get(AiRequest, UUID(response.json()["ai_request_id"]))
    assert record.error_code == "unsafe_causal_or_blame_question"
    assert record.fallback_used is True


def _statement(text: str, refs: list[str]) -> dict:
    return {"text": text, "kind": "observation", "evidence_refs": refs}


def _enable_provider(monkeypatch, body: dict):
    settings = get_settings()
    monkeypatch.setattr(settings, "ai_enabled", True)
    monkeypatch.setattr(settings, "ai_api_key", "test-key-not-a-production-secret")
    monkeypatch.setattr(settings, "ai_base_url", "https://ai.test.invalid")
    sent: list[dict] = []

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return body

    def _post(*_args, **kwargs):
        sent.append(kwargs.get("json") or {})
        return _Response()

    monkeypatch.setattr("app.integrations.ai.providers.httpx.post", _post)
    return sent


@pytest.mark.parametrize(
    ("body", "error_code"),
    [
        ({"text": "The deaths were caused by staff at the facility."}, "unsafe_causal_or_blame_language"),
        ({"text": "These are preventable deaths that reflect negligence."}, "unsafe_causal_or_blame_language"),
        (
            {"statements": [_statement("Staff failure explains ANC4.", ["ANC4_COVERAGE"])]},
            "unsafe_causal_or_blame_language",
        ),
        (
            {"statements": [_statement("ANC4 coverage is reported.", ["NOT_IN_PACKAGE"])]},
            "evidence_reference_invalid",
        ),
        (
            {"statements": [{"text": "ANC4 coverage is reported.", "kind": "observation", "evidence_refs": []}]},
            "evidence_reference_missing",
        ),
        ({"statements": [{"text": "ANC4 coverage is reported.", "kind": "speculation"}]}, "schema_invalid"),
    ],
)
def test_unsafe_or_invalid_provider_output_falls_back(client, session, monkeypatch, body, error_code):
    headers, request, _ = _snapshot(client, session)
    sent = _enable_provider(monkeypatch, body)
    response = client.post("/ai/findings", json=request, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["fallback_used"] is True
    assert payload["mode"] == "deterministic"
    record = session.get(AiRequest, UUID(payload["ai_request_id"]))
    assert record.error_code == error_code
    assert sent and sent[0]["response_schema"]["name"] == "hpip.statements.v1"


def test_schema_valid_provider_statements_are_accepted(client, session, monkeypatch):
    headers, request, _ = _snapshot(client, session)
    statement = {
        "text": "ANC4 coverage is below ANC1 coverage in this snapshot.",
        "kind": "observation",
        "evidence_refs": ["ANC4_COVERAGE", "ANC1_COVERAGE"],
    }
    _enable_provider(monkeypatch, {"statements": [statement]})
    response = client.post("/ai/findings", json=request, headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["fallback_used"] is False
    assert payload["mode"] == "provider"
    assert payload["result"]["statements"] == [statement]
    stored = session.get(AiRequest, UUID(payload["ai_request_id"]))
    assert stored.response_json["statements"] == [statement]


def test_validate_statements_accepts_insufficient_evidence_without_refs():
    package = {"indicators": [{"indicator_code": "ANC4_COVERAGE", "raw_value": 40.0}]}
    cleaned, error = validate_statements(
        [{"text": "The evidence cannot answer this question.", "kind": "insufficient_evidence"}], package
    )
    assert error is None
    assert cleaned[0]["evidence_refs"] == []
    _, number_error = validate_statements(
        [{"text": "ANC4 is 77.7 percent.", "kind": "observation", "evidence_refs": ["ANC4_COVERAGE"]}], package
    )
    assert number_error == "unsupported_numeric_claim"

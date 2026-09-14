from uuid import UUID

from sqlalchemy import select

from app.config import get_settings
from app.models import AiRequest, AnalysisSnapshot, OrgUnit
from app.services.evidence import contains_unsupported_number, question_is_unsupported
from tests.conftest import auth_header, login, query_dashboard
from tests.helpers import put_event, put_population, put_raw


def _unit(session, code):
    return session.scalar(select(OrgUnit).where(OrgUnit.code == code))


def _anc_payload(org_unit_id: str, snapshot: dict | None = None) -> dict:
    payload = {
        "org_unit_id": str(org_unit_id),
        "period": "FY2024/25",
        "module": "anc",
        "comparison_period": "FY2023/24",
    }
    if snapshot:
        payload["analysis_snapshot_id"] = snapshot["analysis_snapshot_id"]
        payload["view_hash"] = snapshot["view_hash"]
    return payload


def _dashboard_snapshot(client, headers, org_unit_id, module="anc", period="FY2024/25"):
    dash = query_dashboard(client, headers, org_unit_id, module=module, period=period)
    assert dash.status_code == 201, dash.text
    body = dash.json()
    assert body["analysis_snapshot_id"]
    return body


def test_findings_explain_ask_use_deterministic_fallback(client, session):
    pader = _unit(session, "PADER")
    put_population(session, pader, 2024, 1_000_000, code="AI_POP_2024")
    put_raw(session, pader, "FY2024/25", "ANC1", 40_000)
    put_raw(session, pader, "FY2024/25", "ANC4", 20_000)
    session.commit()
    csrf = login(client, "pader.focal")
    headers = auth_header(csrf)
    snapshot = _dashboard_snapshot(client, headers, pader.id)
    body = _anc_payload(pader.id, snapshot)
    findings = client.post("/ai/findings", json=body, headers=headers)
    assert findings.status_code == 200, findings.text
    payload = findings.json()
    assert payload["fallback_used"] is True
    assert payload["mode"] == "deterministic"
    assert payload["prompt_version"]
    assert payload["evidence_hash"]
    assert "package" not in payload
    assert payload["analysis_snapshot_id"] == snapshot["analysis_snapshot_id"]
    evidence = session.get(AnalysisSnapshot, UUID(snapshot["analysis_snapshot_id"])).evidence_json
    assert evidence["indicators"]
    assert "event_uid" not in str(evidence)

    explain = client.post(
        "/ai/explain",
        json={**body, "indicator_code": "ANC4_COVERAGE"},
        headers=headers,
    )
    assert explain.status_code == 200
    assert explain.json()["result"]["unsupported"] is False
    assert "ANC4" in explain.json()["result"]["text"] or "coverage" in explain.json()["result"]["text"].lower()

    asked = client.post(
        "/ai/ask",
        json={**body, "question": "What is ANC4 coverage in this evidence?"},
        headers=headers,
    )
    assert asked.status_code == 200
    assert asked.json()["fallback_used"] is True
    stored = session.scalars(select(AiRequest)).all()
    assert stored


def test_unsupported_causation_is_refused(client, session):
    pader = _unit(session, "PADER")
    csrf = login(client, "pader.focal")
    headers = auth_header(csrf)
    snapshot = _dashboard_snapshot(client, headers, pader.id)
    response = client.post(
        "/ai/ask",
        json={
            **_anc_payload(pader.id, snapshot),
            "question": "Who caused this and who should be blamed for negligence?",
        },
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["result"]["unsupported"] is True
    assert question_is_unsupported("who caused this preventable death")


def test_mnch_only_cannot_ask_mpdsr(client, session):
    uganda = _unit(session, "UG")
    csrf = login(client, "mnch.only")
    response = client.post(
        "/ai/ask",
        json={
            "org_unit_id": str(uganda.id),
            "period": "FY2024/25",
            "module": "mpdsr",
            "question": "How many maternal deaths were reported?",
        },
        headers=auth_header(csrf),
    )
    assert response.status_code == 403


def test_ai_geography_is_enforced(client, session):
    teso = _unit(session, "TESO")
    csrf = login(client, "acholi.analyst")
    response = client.post(
        "/ai/findings",
        json={"org_unit_id": str(teso.id), "period": "FY2024/25", "module": "anc"},
        headers=auth_header(csrf),
    )
    assert response.status_code == 403


def test_mpdsr_evidence_omits_event_uids(client, session):
    acholi = _unit(session, "ACHOLI")
    put_raw(session, acholi, "FY2024/25", "FRESH_SB", 2, programme_code="MPDSR")
    put_raw(session, acholi, "FY2024/25", "MATERNAL_DEATHS", 1, programme_code="MPDSR")
    put_event(
        session,
        acholi,
        event_uid="TEST_UID_EVT1",
        data_values={"cause": "haemorrhage", "narrative": "identifying free text", "mother_name": "redact-me"},
    )
    session.commit()
    csrf = login(client, "mpdsr.analyst")
    headers = auth_header(csrf)
    snapshot = _dashboard_snapshot(client, headers, acholi.id, module="mpdsr")
    response = client.post(
        "/ai/findings",
        json={
            "org_unit_id": str(acholi.id),
            "period": "FY2024/25",
            "module": "mpdsr",
            "analysis_snapshot_id": snapshot["analysis_snapshot_id"],
            "view_hash": snapshot["view_hash"],
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert "package" not in response.json()
    encoded = str(session.get(AnalysisSnapshot, UUID(snapshot["analysis_snapshot_id"])).evidence_json)
    assert "TEST_UID_EVT1" not in encoded
    assert "event_uid" not in encoded
    assert "identifying free text" not in encoded
    assert "redact-me" not in encoded


def test_provider_numbers_outside_evidence_fall_back(client, session, monkeypatch):
    pader = _unit(session, "PADER")
    put_population(session, pader, 2024, 1_000_000, code="AI_PROV_POP")
    put_raw(session, pader, "FY2024/25", "ANC1", 10_000)
    session.commit()
    settings = get_settings()
    monkeypatch.setattr(settings, "ai_enabled", True)
    monkeypatch.setattr(settings, "ai_api_key", "test-key-not-a-production-secret")
    monkeypatch.setattr(settings, "ai_base_url", "https://ai.test.invalid")

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"text": "Coverage is 99999 percent from an unverified source.", "usage": {"tokens": 9}}

    monkeypatch.setattr("app.integrations.ai.providers.httpx.post", lambda *_args, **_kwargs: _Response())
    csrf = login(client, "pader.focal")
    headers = auth_header(csrf)
    snapshot = _dashboard_snapshot(client, headers, pader.id)
    response = client.post("/ai/findings", json=_anc_payload(pader.id, snapshot), headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["fallback_used"] is True
    assert body["mode"] == "deterministic"
    evidence = session.get(AnalysisSnapshot, UUID(snapshot["analysis_snapshot_id"])).evidence_json
    assert contains_unsupported_number("Coverage is 99999 percent", evidence)


def test_view_only_cannot_generate_ai_report(client, session):
    uganda = _unit(session, "UG")
    csrf = login(client, "view.only")
    response = client.post(
        "/ai/report",
        json={"org_unit_id": str(uganda.id), "period": "FY2024/25", "module": "anc"},
        headers=auth_header(csrf),
    )
    assert response.status_code == 403

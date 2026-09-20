import httpx

from app.config import Settings
from app.integrations.dhis2.aggregate import parse_analytics_rows
from app.integrations.dhis2.errors import Dhis2AuthError, Dhis2TimeoutError
from app.integrations.dhis2.event_analytics import parse_event_aggregate_rows, parse_event_query_rows
from app.integrations.dhis2.http import Dhis2HttpClient
from app.integrations.dhis2.redaction import redact_mapping
from app.integrations.dhis2.tracker import parse_tracker_events


def _settings(**kwargs) -> Settings:
    values = dict(
        app_env="test",
        database_url="sqlite+pysqlite:///:memory:",
        auth_secret="test-secret-value-that-is-32-chars-min",
        # These tests drive the connector against a stubbed transport, which is an enabled
        # deployment as far as the client is concerned; the runtime gate is asserted separately.
        dhis2_enabled=True,
        dhis2_base_url="https://example.test",
        dhis2_username="tester",
        dhis2_password="secret-password",
        dhis2_retry_base_seconds=0,
        dhis2_max_retries=2,
    )
    values.update(kwargs)
    return Settings(**values)


def test_parse_aggregate_and_no_data():
    payload = {
        "headers": [{"name": "dx"}, {"name": "ou"}, {"name": "pe"}, {"name": "value"}],
        "rows": [["TEST_UID_ANC1", "TEST_UID_UG", "202407", "12"]],
        "serverDate": "2024-07-31T00:00:00Z",
    }
    rows = parse_analytics_rows(payload)
    assert rows[0].value == 12
    assert rows[0].item_uid.startswith("TEST_UID_")
    empty = parse_analytics_rows(
        {"headers": payload["headers"], "rows": [], "metaData": {}}
    )
    assert empty == []


def test_parse_event_query_and_tracker():
    query = {
        "headers": [
            {"name": "event"},
            {"name": "ou"},
            {"name": "eventstatus"},
            {"name": "eventdate"},
            {"name": "TEST_UID_DEATH"},
        ],
        "rows": [["TEST_UID_EV1", "TEST_UID_FAC", "ACTIVE", "2024-07-01", "2024-07-01"]],
        "metaData": {"pager": {"page": 1, "pageCount": 1}},
    }
    events = parse_event_query_rows(query, "TEST_UID_PROGRAM")
    assert events[0].status == "ACTIVE"
    tracker = parse_tracker_events(
        {
            "instances": [
                {
                    "event": "TEST_UID_EV2",
                    "status": "COMPLETED",
                    "orgUnit": "TEST_UID_FAC",
                    "program": "TEST_UID_PROGRAM",
                    "occurredAt": "2024-07-02T00:00:00Z",
                    "dataValues": [{"dataElement": "TEST_UID_DEATH", "value": "2024-07-02"}],
                }
            ]
        }
    )
    assert tracker[0].status == "COMPLETED"
    agg = parse_event_aggregate_rows(
        {
            "headers": [{"name": "ou"}, {"name": "pe"}, {"name": "value"}],
            "rows": [["TEST_UID_FAC", "202407", "3"]],
        }
    )
    assert agg[0].value == 3


def test_retry_then_success():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, json={"message": "busy"})
        return httpx.Response(
            200,
            json={"headers": [{"name": "dx"}, {"name": "ou"}, {"name": "pe"}, {"name": "value"}], "rows": []},
        )

    client = Dhis2HttpClient(_settings(), transport=httpx.MockTransport(handler))
    payload = client.get_json("/api/analytics")
    assert payload["rows"] == []
    assert calls["n"] == 2
    client.close()


def test_auth_error_not_retried():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "no"})

    client = Dhis2HttpClient(_settings(), transport=httpx.MockTransport(handler))
    try:
        client.get_json("/api/analytics")
        raise AssertionError("expected auth failure")
    except Dhis2AuthError:
        pass
    finally:
        client.close()


def test_timeout_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("slow")

    client = Dhis2HttpClient(_settings(), transport=httpx.MockTransport(handler))
    try:
        client.get_json("/api/analytics")
        raise AssertionError("expected timeout")
    except Dhis2TimeoutError:
        pass
    finally:
        client.close()


def test_malformed_json():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not-json")

    client = Dhis2HttpClient(_settings(), transport=httpx.MockTransport(handler))
    try:
        client.get_json("/api/analytics")
        raise AssertionError("expected validation error")
    except Exception as exc:
        assert "JSON" in str(exc) or "json" in str(exc).lower() or exc.__class__.__name__ == "Dhis2ValidationError"
    finally:
        client.close()


def test_redaction_excludes_credentials_and_names():
    clean = redact_mapping(
        {"password": "secret-password", "Authorization": "Bearer abc", "patientName": "Jane", "dx": "TEST_UID_X"}
    )
    assert clean["password"] == "[redacted]"
    assert "secret-password" not in str(clean)
    assert clean["dx"] == "TEST_UID_X"

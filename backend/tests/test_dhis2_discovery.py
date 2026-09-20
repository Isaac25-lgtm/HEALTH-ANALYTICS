from __future__ import annotations

import json

from app.config import get_settings
from scripts import dhis2_discovery


class _DiscoveryClient:
    def __init__(self, settings):
        del settings

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def get_json(self, path, params=None):
        if path == "/api/me":
            return {"id": "SUBJECT", "username": "authorised.user", "authorities": []}
        if path == "/api/organisationUnits":
            page = int(params["page"])
            return {
                "organisationUnits": [{"id": f"OU_{page}", "name": f"Unit {page}"}],
                "pager": {"page": page, "pageCount": 2},
            }
        raise AssertionError(path)


def test_confirmed_discovery_fetches_bounded_metadata_proposal(monkeypatch, tmp_path, capsys):
    settings = get_settings()
    monkeypatch.setattr(settings, "dhis2_enabled", True)
    monkeypatch.setattr(settings, "dhis2_base_url", "https://hmis.health.go.ug")
    monkeypatch.setattr(settings, "dhis2_username", "configured-user")
    monkeypatch.setattr(settings, "dhis2_password", "configured-secret")
    monkeypatch.setattr(dhis2_discovery, "Dhis2HttpClient", _DiscoveryClient)
    output = tmp_path / "proposal.json"

    code = dhis2_discovery.main(
        [
            "--resource",
            "me",
            "--resource",
            "org-units",
            "--max-pages",
            "2",
            "--confirm-network-access",
            "--out",
            str(output),
        ]
    )

    assert code == 0
    summary = json.loads(capsys.readouterr().out)
    proposal = json.loads(output.read_text(encoding="utf-8"))
    assert summary["resource_counts"] == {"me": 1, "org-units": 2}
    assert summary["credentials_in_output"] is False
    assert proposal["applied"] is False
    assert proposal["approval_required"] is True
    assert [row["id"] for row in proposal["resources"]["org-units"]["items"]] == ["OU_1", "OU_2"]


def test_discovery_fails_partial_when_page_cap_is_reached(monkeypatch, tmp_path, capsys):
    settings = get_settings()
    monkeypatch.setattr(settings, "dhis2_enabled", True)
    monkeypatch.setattr(settings, "dhis2_base_url", "https://hmis.health.go.ug")
    monkeypatch.setattr(settings, "dhis2_username", "configured-user")
    monkeypatch.setattr(settings, "dhis2_password", "configured-secret")
    monkeypatch.setattr(dhis2_discovery, "Dhis2HttpClient", _DiscoveryClient)

    code = dhis2_discovery.main(
        [
            "--resource",
            "org-units",
            "--max-pages",
            "1",
            "--confirm-network-access",
            "--out",
            str(tmp_path / "partial.json"),
        ]
    )

    assert code == 5
    summary = json.loads(capsys.readouterr().out)
    assert summary["mode"] == "partial"
    assert summary["truncated_resources"] == ["org-units"]

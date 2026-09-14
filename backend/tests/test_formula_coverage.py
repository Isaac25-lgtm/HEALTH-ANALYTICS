import json
from pathlib import Path

from app.domain.indicator_catalog import INDICATOR_CATALOG
from app.domain.modules import MODULE_INDICATORS

MATRIX_PATH = Path(__file__).resolve().parents[2] / "docs" / "project-context" / "FORMULA_COVERAGE_MATRIX.json"


def classification_state(spec: dict | None) -> str:
    """A non-empty spec is not approval: unclassified modes are TBD and counts are never classified."""
    mode = (spec or {}).get("mode")
    if mode in {None, "unclassified"}:
        return "tbd"
    if mode == "neutral_count":
        return "not_classified_count"
    return "approved"


def build_matrix() -> tuple[list[dict], list[str]]:
    by_code = {row["code"]: row for row in INDICATOR_CATALOG}
    matrix, missing = [], []
    for module in ("anc", "intrapartum", "immunization", "mpdsr"):
        for code in sorted(MODULE_INDICATORS[module]):
            row = by_code.get(code)
            if row is None:
                missing.append(code)
                continue
            spec = row.get("formula_spec") or {}
            matrix.append(
                {
                    "module": module,
                    "code": code,
                    "programme": row.get("programme"),
                    "kind": spec.get("kind"),
                    "denominator_type": row.get("denominator_type"),
                    "direction": row.get("direction"),
                    "has_formula": bool(spec),
                    "classification_mode": (row.get("classification_spec") or {}).get("mode"),
                    "classification_state": classification_state(row.get("classification_spec")),
                }
            )
    return matrix, missing


def test_catalogue_coverage_matrix_is_complete_and_machine_readable():
    matrix, missing = build_matrix()
    assert missing == []
    assert {row["code"] for row in matrix} == set().union(*(set(codes) for codes in MODULE_INDICATORS.values()))
    stored = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
    assert stored["indicators"] == matrix
    assert stored["verified_fixture"] is True
    assert stored["invented_thresholds"] is False


def test_unclassified_indicators_are_never_reported_as_approved():
    matrix, _ = build_matrix()
    by_code = {row["code"]: row for row in matrix}
    epi = [by_code[code] for code in MODULE_INDICATORS["immunization"]]
    assert {row["classification_state"] for row in epi} == {"tbd"}
    assert by_code["PERINATAL_REPORTED_DEATHS"]["classification_state"] == "not_classified_count"
    assert by_code["ANC1_COVERAGE"]["classification_state"] == "approved"


def test_security_headers_and_dev_cors(client):
    response = client.get("/health")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"


def test_production_cors_does_not_auto_permit_localhost():
    from app.config import Settings

    settings = Settings(
        app_env="production",
        web_origin="https://hpip.example.test",
        allowed_origins="https://hpip.example.test,http://localhost:3000",
        auth_secret="a-long-production-secret-value-32ch",
        database_url="postgresql+psycopg://hpip:owner-supplied@127.0.0.1:5432/hpip_prod",
    )
    assert "http://localhost:3000" not in settings.cors_origins
    assert "https://hpip.example.test" in settings.cors_origins

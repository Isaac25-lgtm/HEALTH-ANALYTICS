"""Work package L: prototype behaviour must never reach production code.

`index(1).html` is a visual and interaction reference. Its demonstration values, growth rates,
hard-coded populations, invented thresholds and client-side calculation helpers are not
authoritative, and this test keeps them out of the backend.

Synthetic values are still allowed where they are explicitly labelled: tests, fixtures and the
prototype itself.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
PRODUCTION_DIRS = (BACKEND / "app", BACKEND / "scripts", BACKEND / "alembic")

# Patterns copied from, or characteristic of, the HTML prototype.
FORBIDDEN_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\b1\.032\b", "prototype growth-rate divisor"),
    (r"\bsynthBase\b", "prototype synthetic data generator"),
    (r"composite[_ ]?[Ss]core", "prototype composite score"),
    (r"\bfullimm\b", "prototype 'full immunisation' indicator"),
    (r"\bu5mr\b", "prototype under-five mortality indicator"),
    (r"POPULATION_REGISTRY", "prototype population registry object"),
    (r"\bDISTRICT_BY_CODE\b|\bREGION_BY_CODE\b", "prototype geography lookup"),
    (r"\bDQ_FLAGS\b|\bREPORT_JOBS\b|\bMPDSR\.rows\b", "prototype demonstration data"),
)

# Population figures belong in the registry, the approved workbook or a labelled fixture -
# never inline in code.
POPULATION_LITERALS = (
    "45905417",
    "48152090",
    "49554040",
    "240159",
    "248910",
    "2044355",
    "2152700",
)


def _production_files() -> list[Path]:
    files: list[Path] = []
    for directory in PRODUCTION_DIRS:
        files.extend(
            path
            for path in directory.rglob("*.py")
            if "__pycache__" not in path.parts and "historical" not in path.parts
        )
    return files


@pytest.mark.parametrize("pattern,label", FORBIDDEN_PATTERNS)
def test_prototype_behaviour_is_absent_from_production_code(pattern, label):
    compiled = re.compile(pattern)
    offenders = [
        f"{path.relative_to(REPO)}:{index}"
        for path in _production_files()
        for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if compiled.search(line)
    ]
    assert offenders == [], f"{label} found in production code: {offenders}"


def test_population_figures_are_never_hard_coded_in_production_code():
    offenders = []
    for path in _production_files():
        text = path.read_text(encoding="utf-8")
        for literal in POPULATION_LITERALS:
            if literal in text.replace("_", ""):
                offenders.append(f"{path.relative_to(REPO)} contains {literal}")
    assert offenders == []


def test_production_code_never_reads_the_prototype_or_source_workbooks_at_runtime():
    """Only the governed importer and its CLI may open an owner source file."""
    allowed = {"population_workbook.py", "import_population_workbook.py", "import_geojson.py", "geojson_dry_run.py"}
    offenders = []
    for path in _production_files():
        if path.name in allowed:
            continue
        text = path.read_text(encoding="utf-8")
        for marker in (
            "index(1).html",
            "UGANDA_SUBCOUNTIES.json",
            "UGANDA_DISTRICT.json",
            "UGANDA_DISTRICTS.json",
            "Uganda_District_City_Populations",
        ):
            if marker in text:
                offenders.append(f"{path.relative_to(REPO)} references {marker}")
    assert offenders == []


def test_epi_thresholds_remain_unapproved_in_the_catalogue():
    """The prototype invented EPI RAG bands (green 90 / amber 75). The catalogue must not."""
    from app.domain.indicator_catalog import INDICATOR_CATALOG
    from app.domain.modules import MODULE_INDICATORS

    epi = [row for row in INDICATOR_CATALOG if row["code"] in set(MODULE_INDICATORS["immunization"])]
    assert epi
    for row in epi:
        spec = row.get("classification_spec") or {}
        assert spec.get("mode") in {None, "unclassified"}, row["code"]
        assert row.get("green_band") in (None, ""), row["code"]


def test_mpdsr_percentages_keep_their_precision():
    """The prototype displayed MPDSR percentages as whole numbers; the catalogue keeps decimals."""
    from app.domain.indicator_catalog import INDICATOR_CATALOG

    for row in INDICATOR_CATALOG:
        if row.get("programme") == "MPDSR" and row.get("unit") == "%":
            assert (row.get("display_precision") or 0) >= 1, row["code"]

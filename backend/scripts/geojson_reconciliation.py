"""Validate the owner-supplied boundary candidates and report how they reconcile.

Read-only and streaming: the 156 MB sub-county source is processed feature by feature, never
loaded whole. Nothing is imported and no geometry is activated.

Usage (from backend/):
    python scripts/geojson_reconciliation.py                 # print the summary
    python scripts/geojson_reconciliation.py --write-reports # write docs/reconciliation/*
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from json import JSONDecodeError, JSONDecoder
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from app.db.session import get_session_factory  # noqa: E402
from app.models import OrgUnit  # noqa: E402

REPORT_DIR = REPO / "docs" / "reconciliation"
# Uganda's bounding box with a generous margin; anything outside is not a Uganda boundary.
UGANDA_BOUNDS = (28.5, -2.0, 35.5, 4.5)
LARGE_FEATURE_POSITIONS = 50_000

CANDIDATES = (
    {
        "file": "UGANDA_DISTRICT.json",
        "role": "district_city_candidate",
        "expected_features": 146,
        "level": "district",
        "name_property": "District",
        "expected_format": "geojson",
    },
    {
        "file": "UGANDA_SUBCOUNTIES.json",
        "role": "sub_county_candidate",
        "expected_features": 2190,
        "level": "sub_county",
        "name_property": "Sub_County",
        "expected_format": "geojson",
    },
    {
        "file": "UGANDA_DISTRICTS.json",
        "role": "comparison_only",
        "expected_features": 146,
        "level": "district",
        "name_property": "District",
        "expected_format": "esri_json",
    },
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def detect_format(path: Path) -> tuple[str, dict]:
    """Read only the file head to classify the document and capture its declared metadata."""
    with path.open("r", encoding="utf-8-sig") as handle:
        head = handle.read(4096)
    declared = {}
    for key in ("geometryType", "spatialReference", "displayFieldName"):
        if f'"{key}"' in head:
            declared[key] = True
    if '"esriGeometry' in head or '"geometryType"' in head:
        return "esri_json", declared
    if '"FeatureCollection"' in head:
        return "geojson", declared
    return "unknown", declared


def iter_features(path: Path):
    """Stream the top-level features array of a GeoJSON or Esri JSON document."""
    decoder = JSONDecoder()
    buffer = ""
    with path.open("r", encoding="utf-8-sig") as handle:
        while True:
            chunk = handle.read(1 << 20)
            if not chunk:
                raise ValueError("No features array was found.")
            buffer += chunk
            key_at = buffer.find('"features"')
            if key_at < 0:
                buffer = buffer[-64:]
                continue
            colon_at = buffer.find(":", key_at + len('"features"'))
            array_at = buffer.find("[", colon_at + 1) if colon_at >= 0 else -1
            if array_at >= 0:
                buffer = buffer[array_at + 1 :]
                break
        while True:
            buffer = buffer.lstrip()
            if buffer.startswith("]") or not buffer:
                return
            if buffer.startswith(","):
                buffer = buffer[1:].lstrip()
            while True:
                try:
                    item, end = decoder.raw_decode(buffer)
                    break
                except JSONDecodeError:
                    chunk = handle.read(1 << 20)
                    if not chunk:
                        raise ValueError("The features array is truncated or invalid.") from None
                    buffer += chunk
            yield item
            buffer = buffer[end:]


def _walk_positions(node, stats: dict) -> None:
    """Count positions and check coordinate ranges without keeping geometry in memory."""
    if isinstance(node, list):
        if node and all(isinstance(value, int | float) for value in node[:2]) and len(node) >= 2:
            longitude, latitude = float(node[0]), float(node[1])
            stats["positions"] += 1
            if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
                stats["out_of_range"] += 1
            elif not (
                UGANDA_BOUNDS[0] <= longitude <= UGANDA_BOUNDS[2]
                and UGANDA_BOUNDS[1] <= latitude <= UGANDA_BOUNDS[3]
            ):
                stats["outside_uganda"] += 1
            return
        for item in node:
            _walk_positions(item, stats)


@dataclass
class CandidateReport:
    file: str
    role: str
    level: str
    expected_format: str
    detected_format: str = "unknown"
    declared_metadata: dict = field(default_factory=dict)
    sha256: str = ""
    size_bytes: int = 0
    feature_count: int = 0
    expected_features: int = 0
    property_keys: dict = field(default_factory=dict)
    geometry_types: dict = field(default_factory=dict)
    empty_geometry: int = 0
    null_geometry: int = 0
    out_of_range_positions: int = 0
    positions_outside_uganda: int = 0
    total_positions: int = 0
    large_features: list = field(default_factory=list)
    duplicate_identifiers: dict = field(default_factory=dict)
    duplicate_names: dict = field(default_factory=dict)
    qualified_name_collisions: dict = field(default_factory=dict)
    findings: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "file": self.file,
            "role": self.role,
            "level": self.level,
            "expected_format": self.expected_format,
            "detected_format": self.detected_format,
            "declared_metadata": self.declared_metadata,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "feature_count": self.feature_count,
            "expected_features": self.expected_features,
            "property_keys": self.property_keys,
            "geometry_types": self.geometry_types,
            "null_geometry": self.null_geometry,
            "empty_geometry": self.empty_geometry,
            "total_positions": self.total_positions,
            "out_of_range_positions": self.out_of_range_positions,
            "positions_outside_uganda": self.positions_outside_uganda,
            "large_features": self.large_features,
            "duplicate_identifiers": self.duplicate_identifiers,
            "duplicate_names": self.duplicate_names,
            "qualified_name_collisions": self.qualified_name_collisions,
            "findings": self.findings,
        }


def analyse(path: Path, spec: dict) -> CandidateReport:
    report = CandidateReport(
        file=spec["file"],
        role=spec["role"],
        level=spec["level"],
        expected_format=spec["expected_format"],
        expected_features=spec["expected_features"],
    )
    report.sha256 = sha256(path)
    report.size_bytes = path.stat().st_size
    report.detected_format, report.declared_metadata = detect_format(path)
    identifiers: Counter[str] = Counter()
    names: Counter[str] = Counter()
    qualified: Counter[str] = Counter()
    keys: Counter[str] = Counter()
    geometry_types: Counter[str] = Counter()
    for feature in iter_features(path):
        report.feature_count += 1
        attributes = feature.get("properties")
        if attributes is None:
            attributes = feature.get("attributes") or {}
        keys.update(attributes.keys())
        geometry = feature.get("geometry")
        if geometry is None:
            report.null_geometry += 1
            geometry_types["null"] += 1
            coordinates = None
        elif "rings" in geometry:
            geometry_types["esri_rings"] += 1
            coordinates = geometry.get("rings")
        else:
            geometry_types[str(geometry.get("type"))] += 1
            coordinates = geometry.get("coordinates")
        stats = {"positions": 0, "out_of_range": 0, "outside_uganda": 0}
        if coordinates:
            _walk_positions(coordinates, stats)
        if not coordinates or stats["positions"] == 0:
            report.empty_geometry += 1
        report.total_positions += stats["positions"]
        report.out_of_range_positions += stats["out_of_range"]
        report.positions_outside_uganda += stats["outside_uganda"]
        if stats["positions"] >= LARGE_FEATURE_POSITIONS:
            report.large_features.append(
                {
                    "name": attributes.get(spec["name_property"]),
                    "positions": stats["positions"],
                }
            )
        for identifier_key in ("FID", "OBJECTID"):
            if identifier_key in attributes:
                identifiers[f"{identifier_key}={attributes[identifier_key]}"] += 1
        name = str(attributes.get(spec["name_property"]) or "").strip().upper()
        if name:
            names[name] += 1
            district = str(attributes.get("District") or "").strip().upper()
            if spec["level"] == "sub_county" and district:
                qualified[f"{district}::{name}"] += 1
    report.property_keys = dict(sorted(keys.items()))
    report.geometry_types = dict(sorted(geometry_types.items()))
    report.duplicate_identifiers = {key: count for key, count in identifiers.items() if count > 1}
    report.duplicate_names = {key: count for key, count in names.items() if count > 1}
    report.qualified_name_collisions = {key: count for key, count in qualified.items() if count > 1}

    if report.detected_format != report.expected_format:
        report.findings.append(
            f"Detected {report.detected_format}, expected {report.expected_format}."
        )
    if report.feature_count != report.expected_features:
        report.findings.append(
            f"Feature count {report.feature_count} differs from the expected {report.expected_features}."
        )
    if report.null_geometry or report.empty_geometry:
        report.findings.append(
            f"{report.null_geometry} null and {report.empty_geometry} empty geometries."
        )
    if report.out_of_range_positions:
        report.findings.append(f"{report.out_of_range_positions} coordinates outside valid WGS84 ranges.")
    if report.positions_outside_uganda:
        report.findings.append(
            f"{report.positions_outside_uganda} coordinates fall outside the expected Uganda bounding box."
        )
    if report.duplicate_identifiers:
        report.findings.append(
            f"{len(report.duplicate_identifiers)} duplicated feature identifiers "
            f"({', '.join(sorted(report.duplicate_identifiers)[:5])})."
        )
    if report.duplicate_names:
        report.findings.append(f"{len(report.duplicate_names)} duplicated names at this level.")
    if report.qualified_name_collisions:
        report.findings.append(
            f"{len(report.qualified_name_collisions)} district-qualified sub-county name collisions."
        )
    if report.role == "comparison_only":
        report.findings.append(
            "Esri JSON comparison source. It is never treated as the canonical GeoJSON layer."
        )
    return report


def crosswalk(session, report: CandidateReport, spec: dict, path: Path) -> dict:
    """Match feature names against organisation units, exactly and case-insensitively only."""
    level = "district" if spec["level"] == "district" else "sub_county"
    units = session.scalars(
        select(OrgUnit).where(OrgUnit.active.is_(True), OrgUnit.level_type.in_([level, "city"]))
    ).all()
    by_name: dict[str, list[OrgUnit]] = {}
    for unit in units:
        by_name.setdefault(unit.name.strip().upper(), []).append(unit)
    matched, unmatched, ambiguous = 0, 0, 0
    unmatched_examples: list[str] = []
    for feature in iter_features(path):
        attributes = feature.get("properties") or feature.get("attributes") or {}
        name = str(attributes.get(spec["name_property"]) or "").strip().upper()
        candidates = by_name.get(name, [])
        if len(candidates) == 1:
            matched += 1
        elif len(candidates) > 1:
            ambiguous += 1
        else:
            unmatched += 1
            if len(unmatched_examples) < 15:
                unmatched_examples.append(name.title())
    reference = "authoritative_org_units" if len(units) >= 146 else "synthetic_development_fixtures"
    return {
        "reference_scope": reference,
        "internal_units_at_level": len(units),
        "matched_exact": matched,
        "ambiguous": ambiguous,
        "production_unresolved": unmatched,
        "unmatched_examples": unmatched_examples,
    }


def _markdown(payload: dict) -> str:
    lines = [
        "# Boundary (GeoJSON) reconciliation",
        "",
        f"Generated {payload['generated_at']} by `scripts/geojson_reconciliation.py`. Read-only and "
        "streaming; no geometry was imported or activated.",
        "",
        "## Candidate sources",
        "",
        "| File | Role | Format | Features | Expected | SHA-256 |",
        "|---|---|---|---|---|---|",
    ]
    for item in payload["candidates"]:
        lines.append(
            f"| `{item['file']}` | {item['role']} | {item['detected_format']} | {item['feature_count']} | "
            f"{item['expected_features']} | `{item['sha256'][:16]}…` |"
        )
    for item in payload["candidates"]:
        lines.extend(
            [
                "",
                f"### {item['file']}",
                "",
                f"- Size: {item['size_bytes']:,} bytes",
                f"- Property keys: {', '.join(f'`{key}` ({count})' for key, count in item['property_keys'].items())}",
                f"- Geometry types: {item['geometry_types']}",
                f"- Coordinates: {item['total_positions']:,} positions, "
                f"{item['out_of_range_positions']} outside WGS84 range, "
                f"{item['positions_outside_uganda']} outside the Uganda bounding box",
                f"- Null geometry: {item['null_geometry']}; empty geometry: {item['empty_geometry']}",
                f"- Duplicate identifiers: {item['duplicate_identifiers'] or 'none'}",
                f"- Duplicate names at this level: {len(item['duplicate_names'])}",
                f"- District-qualified sub-county collisions: {len(item['qualified_name_collisions'])}",
                f"- Unusually large features (>= {LARGE_FEATURE_POSITIONS:,} positions): "
                f"{item['large_features'] or 'none'}",
                "",
                "Findings:",
            ]
        )
        lines.extend(f"- {finding}" for finding in item["findings"] or ["No structural problems found."])
        crosswalk_data = item.get("crosswalk")
        if crosswalk_data:
            lines.extend(
                [
                    "",
                    f"Crosswalk against {crosswalk_data['internal_units_at_level']} internal organisation units "
                    f"({crosswalk_data['reference_scope']}):",
                    "",
                    f"- exact matches: {crosswalk_data['matched_exact']}",
                    f"- ambiguous: {crosswalk_data['ambiguous']}",
                    f"- production-unresolved: {crosswalk_data['production_unresolved']}",
                ]
            )
            if crosswalk_data["reference_scope"] == "synthetic_development_fixtures":
                lines.append(
                    "- **These matches are against synthetic development fixtures. None of them is a "
                    "production boundary mapping.**"
                )
    lines.extend(
        [
            "",
            "## Effective date",
            "",
            f"**{payload['effective_date_status']}** — no boundary effective date has been supplied or "
            "verified by the owner. Geometry cannot be activated until it is: "
            "`apply_geometry_import` refuses unless the caller passes `effective_date_verified`, and the "
            "CLI requires `--effective-date-verified`. No date is invented to satisfy the column.",
            "",
            "## Rules that still apply",
            "",
            "- The organisation-unit registry supplies identity and hierarchy; GeoJSON supplies geometry only.",
            "- A map renders exactly the authorised snapshot cohort at one coherent geography level.",
            "- District boundaries never stand in for region boundaries; dissolved higher-level polygons may "
            "only be generated later from approved membership and approved district geometry.",
            "- Missing geometry never means missing health data, and the browser performs no calculation.",
            "- Name similarity is not approval: every mapping needs an explicit, audited decision.",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source-dir", type=Path, default=REPO)
    parser.add_argument("--write-reports", action="store_true")
    parser.add_argument("--skip-crosswalk", action="store_true", help="Structure only; do not open the database.")
    args = parser.parse_args(argv)

    from datetime import UTC, datetime

    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "effective_date_status": "effective date not yet verified",
        "candidates": [],
    }
    session = None if args.skip_crosswalk else get_session_factory()()
    try:
        for spec in CANDIDATES:
            path = args.source_dir / spec["file"]
            if not path.is_file():
                payload["candidates"].append({**spec, "findings": ["File not found."], "feature_count": 0})
                continue
            report = analyse(path, spec)
            item = report.as_dict()
            if session is not None and spec["role"] != "comparison_only":
                item["crosswalk"] = crosswalk(session, report, spec, path)
            payload["candidates"].append(item)
    finally:
        if session is not None:
            session.rollback()
            session.close()

    if args.write_reports:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        (REPORT_DIR / "GEOJSON_RECONCILIATION.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        (REPORT_DIR / "GEOJSON_RECONCILIATION.md").write_text(_markdown(payload), encoding="utf-8")
        payload["reports_written"] = [
            "docs/reconciliation/GEOJSON_RECONCILIATION.json",
            "docs/reconciliation/GEOJSON_RECONCILIATION.md",
        ]
    summary = {
        "effective_date_status": payload["effective_date_status"],
        "candidates": [
            {
                "file": item["file"],
                "detected_format": item.get("detected_format"),
                "features": item.get("feature_count"),
                "findings": item.get("findings"),
                "crosswalk": item.get("crosswalk"),
            }
            for item in payload["candidates"]
        ],
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

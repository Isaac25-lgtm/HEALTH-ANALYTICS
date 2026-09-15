# Boundary (GeoJSON) reconciliation

Generated 2026-09-15T14:45:24.055045+00:00 by `scripts/geojson_reconciliation.py`. Read-only and streaming; no geometry was imported or activated.

## Candidate sources

| File | Role | Format | Features | Expected | SHA-256 |
|---|---|---|---|---|---|
| `UGANDA_DISTRICT.json` | district_city_candidate | geojson | 146 | 146 | `5a6024f5438cf38b…` |
| `UGANDA_SUBCOUNTIES.json` | sub_county_candidate | geojson | 2190 | 2190 | `49c0d09380c5d9e7…` |
| `UGANDA_DISTRICTS.json` | comparison_only | esri_json | 146 | 146 | `9b406b469445e7be…` |

### UGANDA_DISTRICT.json

- Size: 47,405,738 bytes
- Property keys: `District` (146), `FID` (146), `RCode` (146)
- Geometry types: {'MultiPolygon': 4, 'Polygon': 142}
- Coordinates: 489,872 positions, 0 outside WGS84 range, 0 outside the Uganda bounding box
- Null geometry: 0; empty geometry: 0
- Duplicate identifiers: none
- Duplicate names at this level: 0
- District-qualified sub-county collisions: 0
- Unusually large features (>= 50,000 positions): none

Findings:
- No structural problems found.

Crosswalk against 3 active internal organisation units at this level (reference scope `synthetic_development_fixtures`, hierarchy approval reference: not supplied):

| Measure | Features |
|---|---|
| `source_features` | 146 |
| `reconciliation_matched` | 3 |
| `reconciliation_unmatched` | 143 |
| `ambiguous` | 0 |
| `invalid` | 0 |
| `duplicate_targets` | 0 |
| `production_resolved` | 0 |
| **`production_unresolved`** | **146** |
| `non_production_candidates` | 3 |

Non-production candidates (name matches that are **not** boundary mappings): KITGUM, PADER, SOROTI.
- **No owner-approved hierarchy is recorded for this level, so every feature is production-unresolved.**

### UGANDA_SUBCOUNTIES.json

- Size: 163,183,068 bytes
- Property keys: `County` (2190), `District` (2190), `FID` (2190), `FScode` (2190), `OBJECTID` (2190), `RCode` (2190), `Shape_Area` (2190), `Shape_Leng` (2190), `Sub_County` (2190)
- Geometry types: {'MultiPolygon': 110, 'Polygon': 2080}
- Coordinates: 1,671,234 positions, 0 outside WGS84 range, 0 outside the Uganda bounding box
- Null geometry: 0; empty geometry: 0
- Duplicate identifiers: {'OBJECTID=1240': 2}
- Duplicate names at this level: 44
- District-qualified sub-county collisions: 0
- Unusually large features (>= 50,000 positions): none

Findings:
- 1 duplicated feature identifiers (OBJECTID=1240).
- 44 duplicated names at this level.

Crosswalk against 1 active internal organisation units at this level (reference scope `synthetic_development_fixtures`, hierarchy approval reference: not supplied):

| Measure | Features |
|---|---|
| `source_features` | 2190 |
| `reconciliation_matched` | 0 |
| `reconciliation_unmatched` | 2190 |
| `ambiguous` | 0 |
| `invalid` | 0 |
| `duplicate_targets` | 0 |
| `production_resolved` | 0 |
| **`production_unresolved`** | **2190** |
| `non_production_candidates` | 0 |

- **No owner-approved hierarchy is recorded for this level, so every feature is production-unresolved.**

### UGANDA_DISTRICTS.json

- Size: 19,842,192 bytes
- Property keys: `District` (146), `FID` (146), `RCode` (146)
- Geometry types: {'esri_rings': 146}
- Coordinates: 489,872 positions, 0 outside WGS84 range, 0 outside the Uganda bounding box
- Null geometry: 0; empty geometry: 0
- Duplicate identifiers: none
- Duplicate names at this level: 0
- District-qualified sub-county collisions: 0
- Unusually large features (>= 50,000 positions): none

Findings:
- Esri JSON comparison source. It is never treated as the canonical GeoJSON layer.

## Effective date

**effective date not yet verified** — no boundary effective date has been supplied or verified by the owner. `apply_geometry_import` refuses activation unless the hierarchy for the level is owner-approved (`BOUNDARY_DISTRICT_HIERARCHY_APPROVAL_REFERENCE` or `BOUNDARY_SUB_COUNTY_HIERARCHY_APPROVAL_REFERENCE`) and complete, the mapping is unambiguous with a recorded mapping decision reference, and the effective date has a recorded approval reference confirmed with `--effective-date-verified`. No date or reference is invented.

## Rules that still apply

- The organisation-unit registry supplies identity and hierarchy; GeoJSON supplies geometry only.
- A map renders exactly the authorised snapshot cohort at one coherent geography level.
- District boundaries never stand in for region boundaries; dissolved higher-level polygons may only be generated later from approved membership and approved district geometry.
- Missing geometry never means missing health data, and the browser performs no calculation.
- Name similarity is not approval: every mapping needs an explicit, audited decision.

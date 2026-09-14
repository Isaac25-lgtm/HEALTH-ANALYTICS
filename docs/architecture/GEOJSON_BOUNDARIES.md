# Owner-Supplied Geography Boundaries

## Status

The three boundary files added on 2026-09-12 are preserved as source inputs. They have been inspected and validated, but they have **not** been imported into a database. The repository currently contains only a small synthetic development hierarchy, not the approved national organisation-unit master needed for a complete and unambiguous match.

| File | Format | Features | SHA-256 | Decision |
|---|---|---:|---|---|
| `UGANDA_DISTRICT.json` | GeoJSON FeatureCollection | 146 districts | `5a6024f5438cf38bbf1ea822ed4bc1d900005288585bd55294b29d730d7027b8` | Canonical district import candidate |
| `UGANDA_SUBCOUNTIES.json` | GeoJSON FeatureCollection | 2,190 sub-counties | `49c0d09380c5d9e7db824806217f1c8a6a072d7439342609b83dfdd2d5d29936` | Canonical sub-county import candidate |
| `UGANDA_DISTRICTS.json` | Esri JSON | 146 districts | `9b406b469445e7be1f512a0e6f2a0726c743dc1ce7cb7452feb7ab8ce7f9cad5` | Retain as an alternate source; do not import as GeoJSON |

Both GeoJSON files passed the streaming parser, supported-geometry, non-empty-coordinate, and WGS84 range checks. The district properties are `FID`, `District`, and `RCode`. The sub-county properties are `FID`, `OBJECTID`, `Sub_County`, `County`, `District`, `RCode`, `Shape_Leng`, `Shape_Area`, and `FScode`.

## Import contract

`backend/scripts/import_geojson.py` is dry-run by default. It hashes and streams the file rather than loading the roughly 160 MB sub-county source into memory. Matching is conservative:

- District features match a unique active district/city by normalized canonical name.
- Sub-county features match a unique active sub-county by both district ancestor and normalized canonical name.
- Invalid geometry, ambiguous names, or duplicate target units block the entire apply operation.
- Unmatched features also block apply unless `--allow-unmatched` is explicitly used after reviewing the report.
- Apply requires `--user` for an active user with `manage_mappings` and an explicit `--valid-from` date.
- A new dataset versions existing current geometry by closing the prior validity interval and records one audit event. Re-applying the same file hash is idempotent.

Example dry run from `backend/`:

```powershell
python scripts/import_geojson.py ..\UGANDA_DISTRICT.json --level district
python scripts/import_geojson.py ..\UGANDA_SUBCOUNTIES.json --level sub_county
```

Do not use `--apply` until the approved national analytical hierarchy, city treatment, canonical names/codes, and boundary effective date are confirmed. Against the synthetic seed only, the district source matched 3 of 146 units and the sub-county source matched 0 of 2,190. This is expected and is not evidence of bad geometry.

## Adaptive map data contract

`GET /org-units/{org_unit_id}/map-geometry?as_of=YYYY-MM-DD` returns a permission-filtered GeoJSON FeatureCollection for the nearest mapped descendant level:

- Uganda or region/sub-region selection returns the nearest available district/city polygons.
- District/city selection returns the nearest available sub-county polygons.
- A leaf selection falls back to its own polygon or point when present.
- `unmapped_units` explicitly lists eligible units without geometry. No geometry never means no health data.
- Responses include validity dates, use private browser caching, and are gzip-compressed by the API for large national layers.
- When no approved mapping has been applied, `mapping_state` is `boundaries_awaiting_approved_mapping` and `feature_count` is 0.
- `?simplify=true` returns a copied, versioned Ramer–Douglas–Peucker simplification (`hpip-rdp-1`). Source files and stored authoritative geometry are not overwritten.

## Snapshot map cohort (amendment 2026-09-13)

Dashboards no longer join a separately fetched geometry layer in the browser. `POST /analytics/dashboard/query` stores a `map` block in the snapshot:

- `map_level` (one aggregation class), `map_level_types`, `map_parent_org_unit_id`, `selected_indicator`;
- `map_feature_org_unit_ids` — exactly the authorised value rows that have geometry, one feature per row;
- `map_value_run_ids`, `geometry_effective_date` (the period end), `geometry_versions`, `missing_geometry_ids`, `missing_value_ids`;
- `map_state`: `mapped`, `geometry_unavailable_for_level`, `mixed_levels_not_mapped`, or `no_map_units`.

`GET /analysis-snapshots/{id}/map-features` returns those features with values copied from the snapshot and access re-checked. District polygons are never substituted for regions; district screens map facility points or polygons, not the district outline. The browser performs no calculation and no `as_of` derivation.

The earlier Phase 4 map joined the features below to authorised dashboard comparison values by organisation-unit ID. It does not calculate indicators in the browser or load the owner source set in the client. A 2026-09-12 dry-run report is stored at `docs/architecture/GEOJSON_DRY_RUN.json`. Name matches against the synthetic seed are not approved production mappings.

## Validation and reconciliation (2026-09-14)

`python scripts/geojson_reconciliation.py --write-reports` streams all three candidates and writes `docs/reconciliation/GEOJSON_RECONCILIATION.{md,json}`:

- `UGANDA_DISTRICT.json`: GeoJSON, 146 features (142 Polygon, 4 MultiPolygon), 489,872 positions, all within WGS84 range and the Uganda bounding box, no null or empty geometry, no duplicate identifiers or names.
- `UGANDA_SUBCOUNTIES.json`: GeoJSON, 2,190 features (2,080 Polygon, 110 MultiPolygon), 1,671,234 positions, all in range. `OBJECTID=1240` is shared by two different features; 44 sub-county names repeat nationally, with no collision once qualified by district.
- `UGANDA_DISTRICTS.json`: Esri JSON (`esriGeometryPolygon`, wkid 4326), 146 features — comparison only, never canonical.

Crosswalk results are against synthetic development fixtures and are not production mappings. **Effective date not yet verified.** `apply_geometry_import` now refuses unless the caller passes `effective_date_verified=True`, and `scripts/import_geojson.py --apply` requires `--effective-date-verified`; no date is invented to satisfy the column.

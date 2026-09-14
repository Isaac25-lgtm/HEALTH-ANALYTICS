# Analytical geography hierarchy

Primary hierarchy:

`Uganda → Region/Sub-region → District/City → Sub-county → Health Facility`

Internal organisation units use stable UUIDs. DHIS2 UIDs live only in `org_unit_mappings`.

## Capabilities

Implemented in `backend/app/services/geography.py`:

- parent/child relationships and materialized `path`
- organisation-unit type (`country`, `region`, `sub_region`, `district`, `city`, `sub_county`, `facility`)
- historical validity and active/inactive state
- ancestor and descendant resolution
- authorised-subtree queries (API re-checks geography permission)
- cycle prevention on parent assignment
- bulk-import validation
- reconciliation of unmapped DHIS2 organisation-unit UIDs
- optional `org_unit_groups` for future analytical groupings without changing the primary tree
- streaming validation/versioning for owner-supplied district and sub-county GeoJSON
- adaptive map geometry resolution to the nearest mapped descendant level

Acholi, Pader, Teso, Kitgum, Soroti, and Pader HC III appear only as **synthetic regression fixtures**. They are not the national structure.

## APIs

- `GET /org-units/{id}`
- `GET /org-units/{id}/children`
- `GET /org-units/{id}/ancestors`
- `GET /org-units/{id}/map-geometry?as_of=YYYY-MM-DD`

Each requires `view` plus geography membership. A facility user cannot read a parent district. A district user cannot read a sibling district.

See [Owner-Supplied Geography Boundaries](GEOJSON_BOUNDARIES.md) for verified file hashes, feature counts, dry-run/apply controls, and the reason the source files remain unimported until the approved national hierarchy is available.

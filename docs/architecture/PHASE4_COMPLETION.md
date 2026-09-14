# Phase 4 completion report

**Date:** 2026-09-12  
**Status:** Phase 4 dashboard experience passed the automated gate. Phase 5 was not started.

> **Superseded route (2026-09-13 amendment §1/§13):** `GET /analytics/dashboard` created runs and snapshots and was removed. Dashboards execute through `POST /analytics/dashboard/query`, re-open with `GET /analysis-snapshots/{id}`, and map from `GET /analysis-snapshots/{id}/map-features`. See `API_AUTH.md` and `GEOJSON_BOUNDARIES.md`. This report is kept as a historical record and is not an acceptance statement.

## Screens

| Screen | Route | API |
|---|---|---|
| National | `/dashboard/national` | `GET /analytics/dashboard` |
| Regional / sub-regional | `/dashboard/regional` | same |
| District facility performance | `/dashboard/district` | same; comparison grain is descendant facilities |
| Individual facility | `/dashboard/facility` | same, plus optional catchment draft POST |

The home route redirects to the highest authorised landing screen. URL parameters never expand server-side geography or programme authority.

## Design system

Reusable navy sidebar shell, filter bar, KPI cards, scorecards, RAG/BLUE pills with text/icon cues, SVG trends, tables, alerts, evidence/methodology drawer, freshness line, loading/error/no-data/permission-denied states, map legend, and visible-but-disabled Phase 6 export actions.

BLUE is labelled “Non-assessable” and is not treated as high performance. Tabular numerals are used for analytical values. Missing remains distinct from a reported zero. Population-derived indicators degrade only when the approved denominator is absent.

## Maps

`GET /org-units/{id}/map-geometry` remains the only browser geometry source. The UI does not load the ~219 MB owner files. When no approved mapping has been applied, the map shows **Boundaries awaiting approved mapping**. Optional deterministic response simplification (`simplify=true`, version `hpip-rdp-1`) copies geometry and does not overwrite source files.

Dry-run importer evidence: `docs/architecture/GEOJSON_DRY_RUN.json`. Against the synthetic seed only, `UGANDA_DISTRICT.json` name-matched 3 of 146 features and `UGANDA_SUBCOUNTIES.json` matched 0 of 2,190. Those incidental name matches were **not applied**.

## Frontend verification

From `frontend/` on 2026-09-12, using project-local ESLint 9 + `eslint-config-next@15.5.25`:

- `npx tsc --noEmit` — exit 0
- `npx eslint .` — exit 0
- `npx vitest run` — 9 passed
- `npx next build` — exit 0 after isolating `distDir` to `.next-build` (the previous hang was a locked `.next` directory on Windows)
- `npx playwright test` — 3 passed (cookie/CSRF login, four-screen navigation, unauthorised URL denial, logout)

Playwright starts a disposable SQLite API on port **8010** so it does not bind the workstation’s existing port 8000 process.

## Not delivered (by design)

Phase 5 AI, Phase 6 publishing engines, Phase 7 production deployment, live DHIS2, invented populations, invented facility coordinates, and applied national boundary mappings.

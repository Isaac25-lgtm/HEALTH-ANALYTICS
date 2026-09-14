# Architecture overview

The platform is a **national, role-aware analytical layer above DHIS2**, not a second data-entry system.

```
DHIS2 / approved imports
        ↓  (Phase 2)
raw cache + metadata mappings
        ↓  (Phase 2)
population + indicator registry
        ↓  (Phase 2)
deterministic calculation + data-quality engines
        ↓
versioned analytics store
        ↓
permission-filtered APIs  ← Phase 1 delivers this boundary
        ↓
dashboard / AI gateway / Excel-PPTX-report publishing  (Phases 4–6)
```

Phase 1 delivered architecture, schema, and server-side authorisation.

Phase 2 delivered the data foundation:

1. DHIS2 aggregate, Event Analytics, and Tracker adapters with mocked contract tests
2. Versioned mappings and raw snapshot persistence
3. Geography services and versioned population resolution
4. Constrained indicator calculation and reproducible runs
5. A separate data-quality engine

Later modules and screens must call the same authorisation services. Hiding a control in the UI is not security.

## Runtime services

- **hpip-api** (`backend/`): FastAPI.
- **hpip-web** (`frontend/`): Next.js App Router.
- **PostgreSQL** (+ PostGIS when available): system of record.
- **Redis / Celery**: production sync uses the queue. Tests may execute jobs eagerly. Celery is an optional extra.
- **DHIS2**: adapters implemented; live verification pending.
- **AI / publishing modules**: package boundaries only.

## Permission model

Every data request is the intersection of:

- Geography (org unit and descendants)
- Programme (`MNCH`, `EPI`, `MPDSR` in the first release)
- Action (`view`, `export`, `generate_ai_report`, `edit_population`, admin actions, and distinct MPDSR event/line-list actions)

Landing geography is the highest authorised organisational unit (`GET /me/context`).

## Phase 2 notes

- [DHIS2 connectors](DHIS2_CONNECTORS.md)
- [Metadata mappings](METADATA_MAPPINGS.md)
- [Geography](GEOGRAPHY.md)
- [Owner-supplied GeoJSON boundaries](GEOJSON_BOUNDARIES.md)
- [Population](POPULATION.md)
- [Calculation engine](CALCULATION_ENGINE.md)
- [Data quality](DATA_QUALITY.md)
- [Provenance](PROVENANCE.md)
- [Operations runbook](OPERATIONS_RUNBOOK.md)
- [Synthetic fixtures](SYNTHETIC_FIXTURES.md)
- [Phase 2 completion](PHASE2_COMPLETION.md)

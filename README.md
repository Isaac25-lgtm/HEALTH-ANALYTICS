# Uganda Health Performance Intelligence Platform

National analytical layer above DHIS2. First production module: MNCH (ANC, intrapartum/newborn, immunization/EPI, MPDSR).

**Current status (2026-09-14):** pre-DHIS2 UAT preparation for Render + Neon. Phases 1–7 plus corrective work are implemented: persistent analytical snapshots, queued exports with durable failure and database-backed artifacts, retention and purge, MPDSR minimisation, a central population/period resolver, governed population staging, boundary reconciliation and a same-origin frontend. Alembic head is `0011_population_import_staging`. **Nothing is deployed, DHIS2 is not connected, and nothing is owner-accepted.** Owner inputs in `docs/project-context/OPEN_ITEMS.md` remain unresolved.

Do not treat passing local tests as production acceptance.

## Canonical sources

- `ULTIMATE_IDE_HANDOFF_Uganda_Health_Performance_Intelligence_Platform.md`
- `docs/project-context/`
- `AGENTS.md`

## Layout

| Path | Role |
|---|---|
| `backend/` | FastAPI API, domain services, SQLAlchemy models, Alembic, tests |
| `frontend/` | Next.js application (authorised dashboards, maps, AI, exports) |
| `docs/architecture/` | Architecture, schema, auth, engines, and operations notes |
| `docs/project-context/` | Binding product context |
| `docker-compose.dev.yml` | Development API/web (SQLite, explicit development gates) |
| `docker-compose.yml` | Production-like stack: PostgreSQL, Redis, migrations, API, worker, web; no default credentials |
| `render.yaml` | Render UAT blueprint (web, API, one worker, Redis, purge cron, inert DHIS2 refresh); Neon is external |
| `docs/reconciliation/` | Population workbook and boundary reconciliation reports |
| `docs/DEPLOYMENT.md` | Render + Neon runbook, retention, backup, rotation |

## Phase status

| Phase | Status |
|---|---|
| 1. Foundations and security | Implemented with cookie/CSRF/JTI and corrective CORS/headers. Owner acceptance still required. |
| 2. Connectors, geography, population, calculation, quality | Implemented. Live DHIS2 and district populations pending. |
| 3. MNCH analytical modules | Implemented. Independent VERIFIED FIXTURE numerators replaced tautological gold loaders. EPI bands remain TBD. |
| 4. Dashboard and maps | Implemented with specialised geography/workspace routes and MapLibre rendering of permission-filtered server geometry. Source GeoJSON remains unimported. |
| 5. AI | Deterministic fallback and exact-snapshot evidence. No approved provider configured. |
| 6. Publishing | Snapshot-bound Excel/PPTX/report artifacts through the Celery queue with bounded retries, durable failure state, 24-hour artifact expiry and database artifact storage for Render. Official MoH templates pending. |
| 7. Hardening | CI (PostgreSQL, Redis, Playwright, containers), fail-closed production validation, retention purge, Render blueprint. Production readiness fails closed until owner inputs arrive. |

Live DHIS2: the host is known (`https://hmis.health.go.ug`); credentials, metadata mappings, authenticated access and live synchronisation are not available. `DHIS2_ENABLED=false`.

## Quick start

See `docs/architecture/LOCAL_DEVELOPMENT.md`.

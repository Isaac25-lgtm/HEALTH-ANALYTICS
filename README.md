# Uganda Health Performance Intelligence Platform

National analytical layer above DHIS2. First production module: MNCH (ANC, intrapartum/newborn, immunization/EPI, MPDSR).

**Current status:** Phases 1–7 exist in the repository. A 2026-09-12 corrective pass implemented persistent analytical snapshots, exact-run AI/exports, hierarchy/mapping/MPDSR isolation, and security-header/CORS hardening. **This is not a live go-live.** Owner inputs in `docs/project-context/OPEN_ITEMS.md` remain unresolved.

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
| `docker-compose.dev.yml` | Development API/web images only |
| `docker-compose.yml` | Optional PostgreSQL/PostGIS + Redis |

## Phase status

| Phase | Status |
|---|---|
| 1. Foundations and security | Implemented with cookie/CSRF/JTI and corrective CORS/headers. Owner acceptance still required. |
| 2. Connectors, geography, population, calculation, quality | Implemented. Live DHIS2 and district populations pending. |
| 3. MNCH analytical modules | Implemented. Independent VERIFIED FIXTURE numerators replaced tautological gold loaders. EPI bands remain TBD. |
| 4. Dashboard and maps | Implemented with specialised geography/workspace routes and MapLibre rendering of permission-filtered server geometry. Source GeoJSON remains unimported. |
| 5. AI | Deterministic fallback and exact-snapshot evidence. No approved provider configured. |
| 6. Publishing | Snapshot-bound Excel/PPTX/report artifacts with queued job lifecycle. Test/dev may generate eagerly. Official MoH templates pending. |
| 7. Hardening | CI/Docker/docs exist. Production readiness fails closed until owner inputs arrive. |

Live DHIS2: connector implementation complete; live verification pending authorised endpoint configuration and credentials.

## Quick start

See `docs/architecture/LOCAL_DEVELOPMENT.md`.

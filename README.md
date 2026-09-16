# Uganda Health Performance Intelligence Platform

A national analytical layer above DHIS2. Deterministic indicators, permission-scoped dashboards,
maps, data-quality diagnostics, evidence-bound AI interpretation and publication-ready exports.
First production module: **MNCH** — antenatal care, intrapartum and newborn, immunisation/EPI and
MPDSR.

> **Status — 2026-09-16 · pre-UAT, not deployed.**
> Phases 1–7 and four corrective passes are implemented and locally verified. **Nothing is
> deployed, live DHIS2 is not connected, no production population or boundary is activated, and
> nothing is owner-accepted.** Passing tests are not acceptance. Outstanding owner inputs are
> tracked in [`docs/project-context/OPEN_ITEMS.md`](docs/project-context/OPEN_ITEMS.md).

---

## What it does

| Capability | Behaviour |
|---|---|
| **Deterministic calculation** | Every value comes from a versioned indicator formula, a recorded population version and a committed calculation snapshot. The browser never calculates. |
| **Three-dimensional authorisation** | Geography × programme × action, enforced server-side on every request. Changing a URL never widens access. |
| **Honest missing data** | Missing stays missing. Nothing is silently capped, imputed or turned into zero; each unavailable value carries a reason code. |
| **Data quality** | Completeness, consistency, outlier and lineage checks with an explicit flag console, plus "why is this red?" drill-down. |
| **Maps** | MapLibre rendering of permission-filtered server geometry only. No boundary is substituted from another level. |
| **AI, evidence-bound** | AI interprets a verified evidence package; it never invents numbers. A deterministic fallback answers when no provider is configured. |
| **Publishing** | Snapshot-bound Excel, PowerPoint and narrative artifacts through a durable queue with bounded retries and expiring artifacts. |
| **MPDSR minimisation** | Structured cause codes only, no free text, strict formats, short retention and suppression below an approved minimum cell count. |

## Architecture

```mermaid
flowchart LR
  B["Browser<br/>cookie session + CSRF"] --> W["Next.js 15<br/>runtime /api proxy"]
  W --> A["FastAPI<br/>authorisation · calculation · quality"]
  A --> P[("PostgreSQL<br/>control · snapshots · provenance")]
  A --> Q["Celery worker<br/>exports · sync · purge"]
  Q --> R[("Redis")]
  A -. "not connected" .-> D["DHIS2<br/>aggregate + tracker"]
```

The frontend is served same-origin: the production build contains no backend address, and the
`/api` route resolves the backend at request time. Authentication is cookie-only; the browser never
stores a token. PostgreSQL holds control, configuration, snapshot and provenance data — not a copy
of DHIS2.

## Stack

| Layer | Choice |
|---|---|
| API | FastAPI, SQLAlchemy 2, Alembic (head `0012_population_staging_identity`) |
| Workers | Celery with Redis; queues for exports, sync and maintenance |
| Web | Next.js 15 (App Router), React 19, TypeScript, MapLibre |
| Tests | pytest (SQLite + PostgreSQL 18), Vitest, Playwright with a bounded acceptance gate |
| Hosting target | Render blueprint (public web, private API, worker, Key Value, purge cron) with Neon PostgreSQL — **defined, not yet validated by Render** |

## Repository layout

| Path | Role |
|---|---|
| `backend/` | API, domain services, models, Alembic migrations, tests |
| `frontend/` | Next.js application, Playwright suite, acceptance gate |
| `docs/architecture/` | Architecture, schema, auth, engines, operations, local development |
| `docs/project-context/` | Binding product context, decisions, defects, open items |
| `docs/reconciliation/` | Population workbook and boundary reconciliation reports |
| `docs/evidence/` | Acceptance screenshots and the visual comparison matrix |
| `render.yaml`, `docker-compose*.yml` | Deployment blueprint and local stacks |
| `ULTIMATE_IDE_HANDOFF_*.md`, `AGENTS.md` | Canonical specification and working rules |

## Quick start

```bash
# API
cd backend
python -m venv .venv && .venv/Scripts/activate      # Linux/macOS: source .venv/bin/activate
pip install -e ".[dev,worker]"
alembic upgrade head
python scripts/bootstrap_reference_data.py          # approved reference configuration
python scripts/create_initial_admin.py              # reads HPIP_ADMIN_PASSWORD once
uvicorn app.main:app --reload

# Web
cd frontend
npm ci
npm run dev
```

Full instructions, including the disposable PostgreSQL cluster and Playwright setup, are in
[`docs/architecture/LOCAL_DEVELOPMENT.md`](docs/architecture/LOCAL_DEVELOPMENT.md).

## Verification

```bash
# Backend
python -m ruff check app tests scripts alembic
python -m pytest -q -rs

# Frontend
npm run typecheck && npm run lint && npm test && npm run build
npm run verify:proxy     # proves no backend address is baked into the build
npm run e2e              # bounded acceptance gate (below)
```

`npm run e2e` runs the acceptance gate, which owns the build, the disposable API, the production web
server and Playwright as direct children. It fails unless every test passes with no skips, Playwright
exits by itself within a bound of its summary, ports 3000/8010 are free, no process created by the
run survives, the JSON report is fresh, process verification succeeded, and the working tree's status
and content fingerprint are unchanged by the run. Every bound — post-summary, pre-summary
inactivity, overall runtime, build, service stop and each process query — is configurable and fails
closed.

Latest local results (Windows workstation, 2026-09-16):

| Suite | Result |
|---|---|
| Backend, SQLite | 770 passed, 32 skipped (30 PostgreSQL-only, 2 Redis) |
| Backend, PostgreSQL 18 | 800 passed, 2 skipped (Redis) |
| Frontend unit (Vitest) | 103 passed |
| End-to-end (Playwright gate) | 24 passed, 0 skipped, 0 flaky |

CI additionally runs the backend against PostgreSQL and Redis, the frontend build and Playwright,
and container/compose validation. See [`.github/workflows/ci.yml`](.github/workflows/ci.yml).

## Governance rules

These are enforced in code and tests, not just documented:

- No invented formulas, thresholds, populations, DHIS2 UIDs, mappings or branding. Gaps are recorded
  as open items and fail closed.
- Reference bootstrap compares every field it owns and refuses to write on any conflict.
- Boundary activation requires an approved hierarchy, a recorded mapping decision, a checksum and an
  effective-date approval reference. Against the development fixtures the district source reports
  `reconciliation_unmatched = 143`, `non_production_candidates = 3` and `production_unresolved = 146`;
  sub-counties report `production_unresolved = 2,190`.
- Population workbook rows can be staged for review but never become denominators without approval.
- Historical migrations are immutable; configuration changes are audited with before/after values.

## Documentation

| Document | Contents |
|---|---|
| [`OPEN_ITEMS.md`](docs/project-context/OPEN_ITEMS.md) | Owner inputs still required |
| [`DECISION_REGISTER.md`](docs/project-context/DECISION_REGISTER.md) | Owner decisions, kept separate from engineering choices |
| [`DEFECT_MATRIX.md`](docs/project-context/DEFECT_MATRIX.md) | Audited defects, corrections and evidence |
| [`CHANGELOG_CONTEXT.md`](docs/project-context/CHANGELOG_CONTEXT.md) | What changed, with verification results |
| [`DEPLOYMENT.md`](docs/DEPLOYMENT.md) | Render + Neon runbook, retention, backup, rotation |
| [`UI_VISUAL_CONTRACT.md`](docs/project-context/UI_VISUAL_CONTRACT.md) | Visual and interaction contract |

## Phase status

| Phase | State |
|---|---|
| 1. Foundations and security | Implemented (cookie/CSRF/JTI sessions, fail-closed production validation). Owner acceptance required. |
| 2. Connectors, geography, population, calculation, quality | Implemented. Live DHIS2 and approved populations pending. |
| 3. MNCH analytical modules | Implemented against independent verified fixtures. EPI colour bands remain undecided. |
| 4. Dashboards and maps | Implemented per screen and workspace. Source GeoJSON remains unimported. |
| 5. AI | Deterministic fallback and exact-snapshot evidence. No approved provider configured. |
| 6. Publishing | Queued Excel/PPTX/report artifacts with durable failure states. Official templates pending. |
| 7. Hardening | CI, retention purge, Render blueprint, acceptance gate. Blueprint not validated by Render. |

## Not connected

Live DHIS2 (`https://hmis.health.go.ug`) is known but not connected: credentials, metadata mappings
and authenticated synchronisation are unavailable, and `DHIS2_ENABLED=false`. Any credential
disclosed in earlier working material is treated as compromised and is never used.

## Licence

No licence has been declared. All rights reserved by the project owner; ask before reuse.

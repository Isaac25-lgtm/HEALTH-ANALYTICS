# ADR-001 — Application stack

- **Status:** Accepted
- **Date:** 2026-09-11
- **Phase:** 1

## Decision

Use the canonical handoff’s recommended production stack:

- Frontend: React / Next.js + TypeScript + Tailwind CSS
- Backend: Python 3.12 FastAPI
- ORM / migrations: SQLAlchemy 2 + Alembic
- Database: PostgreSQL, with PostGIS available for later geometry work
- Cache / jobs: Redis + Celery (wired as configuration only in Phase 1)
- Auth (Phase 1): local development users + signed JWT; replaceable by the approved identity provider

FastAPI was chosen over Flask because Phase 1 requires typed request/response contracts and the handoff listed FastAPI first while still allowing Flask. Python 3.12 matches prior DHIS2-platform experience recorded in the handoff without inheriting that legacy application.

## Consequences

- Indicator formulas, DHIS2 UIDs, and population values stay in versioned configuration tables, not in UI code.
- SQLite is allowed only for automated tests and isolated local bootstrap. Staging/production must use PostgreSQL.
- Celery is not required to run for Phase 1 tests.
- Official MoH branding assets are not embedded; the frontend shell uses the approved navy/canvas tokens only.

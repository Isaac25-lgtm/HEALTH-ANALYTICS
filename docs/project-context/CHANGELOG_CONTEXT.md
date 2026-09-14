# Context Changelog

## 2026-09-13 — Material amendment to the corrective prompt

Owner supplied a candidate district/city population workbook, an HTML design prototype (layout reference only), and a 17-section material amendment. The base corrective prompt it amends was not received; only the amendment was implemented. Nothing below is owner-accepted.

- Alembic head is `0007_amendment_corrections` (request keys, explicit period-rule scope, population source identity and alias table, sync event windows, value reason codes and event coverage). Existing FY rules were preserved as FY-only.
- Analytical execution moved to CSRF-protected POST routes with request-key idempotency; committed snapshots are re-opened with read-only GETs. The frontend keeps `request`/`snapshot` in the URL so refresh never recalculates.
- Engine: one common aggregation scope, district/city peers, FY-only population rules, facility-only catchment entries, verified-zero MPDSR coverage, direction-aware interpretation and ranking, governed cause disclosure, blame/causation refusal with schema-validated provider statements, freshness ordering, snapshot map cohort, and export labelling/completeness.
- Population workbook: checksum and structure verified, dry-run reconciliation and reviewed-alias importer added. **No population import was performed.**
- Formula coverage matrix corrected: EPI indicators are `tbd`, not `approved`.
- Baseline before changes (owner-reported and re-executed): 210 backend tests, Ruff clean, TypeScript clean, Vitest 9, ESLint 420 errors from `.next-gate`, Playwright unexecuted.
- After changes: backend `pytest` **374 passed, 0 skipped** (SQLite plus PostgreSQL 18 on port 55432; ports 5432/5433 untouched); Ruff clean; TypeScript 0 errors; ESLint 0 errors; Vitest 18 passed; `next build` passed on an isolated scratch copy; Playwright 5 passed against that build and the e2e API.
- `next build` in the project directory hangs because `.next-gate` artifacts from another sandbox identity cannot be deleted by this user and Next.js retries `EPERM` indefinitely. See `OPEN_ITEMS.md`.

## 2026-09-12 — Phases 5–7 for owner audit

Owner authorised completing the remaining phases. AI Gateway, publishing, and hardening are implemented. Official MoH templates, live DHIS2, and production hosting were not invented.

- Alembic head is `0005_phase567_ai_publishing` (export artifact columns and AI request metadata).
- AI: `POST /ai/findings|explain|ask|report` with redacted evidence, deterministic fallback, and provider-number rejection. Dashboard Ask the Data panel is live.
- Publishing: Excel, editable PowerPoint, and markdown reports from calculation runs. MPDSR line-list remains blocked. Dashboard export buttons are live.
- Hardening: export/AI rate limits, admin `GET /ops/status` without secrets, SQLite backup helper that refuses PostgreSQL URLs, labelled Acholi gold fixture, deployment and governance docs.
- Backend `pytest`: **178 passed, 11 skipped** (PostgreSQL Alembic tests skipped; no disposable cluster was started; localhost:5432 was not mutated). Ruff clean.
- Frontend: `tsc` 0, `eslint` 0, Vitest 9 passed, `next build` 0, Playwright 3 passed (e2e API on 8010; Next rebuilds with that origin so cookies are not sent to port 8000).

## 2026-09-12 — Phase 1/2 closure plus Phase 3 and Phase 4

Owner-authorised continuation closed remaining Phase 1/2 verification, then implemented Phase 3 modules and Phase 4 dashboards/maps. Phase 5 was not started.

- Full backend suite after the latest code: **171 passed, 0 skipped** when the disposable PostgreSQL 18 verifier was available.
- Ruff clean over `app`, `tests`, `alembic`/`historical`, and `scripts`.
- Disposable PostgreSQL 18.1 cluster (`initdb` trust, port 55433, role `hpip_verify`) ran 11 Alembic tests against `hpip_p18_alembic_verify` only. Port 5432 was not mutated. The cluster was stopped afterward.
- Phase 3 module API covers ANC, intrapartum/newborn, immunisation, and both MPDSR streams on the shared engines.
- Phase 4 adds `GET /analytics/dashboard` and the four mandatory screens plus adaptive maps. Production boundary import remains blocked.
- Frontend: ESLint flat config matching Next 15.5.25, TypeScript, Vitest (9), production build (`distDir=.next-build`), and Playwright smoke (3). The previous Next banner hang was a locked `.next` directory on Windows.
- GeoJSON dry-run report: `docs/architecture/GEOJSON_DRY_RUN.json`. No boundaries were applied.

## 2026-09-12 — independent Phase 1/2 audit continuation

- Added migration `0004_phase12_audit_fixes` for programme-scoped raw aggregate uniqueness and one current geometry per organisation unit.
- Closed zero-programme-scope list/get authorisation, bound CSRF proof to its session JWT, made sync queue submission fail visibly, and repaired category-option mapping and event-stage ambiguity.
- Rebuilt calculation lineage from the exact raw rows and mappings actually used, with population/facility/freshness references in the immutable run snapshot.
- Added governed bulk population import plus draft approve/reject endpoints; approved values alone appear in ordinary listing/resolution.
- Validated the owner-supplied district/sub-county files and added a streaming, audited geometry importer plus permission-filtered adaptive geometry API. No map screen and no Phase 3 module were started.

## 2026-09-12 — Phase 1/2 corrective implementation

Owner rejected the previous Phase 1/2 implementation. Corrective work repaired migrations, authorisation, cookie-only authentication, aggregation, composites, KMC, population approval, FY periods, indicator contracts, connectors/sync jobs, quality lifecycle, and provenance. Phase 3 was not started.

- Alembic revisions 0001/0002 are explicit frozen schemas; 0003 adds corrective constraints and session tables.
- Programme is mandatory on calculation create; UUID retrieval cannot bypass programme or geography.
- Browser sessions use HTTP-only cookies and CSRF; access tokens are not stored in localStorage.
- Isolated PostgreSQL 16 migration tests passed (5). The workstation PostgreSQL on port 5432 did not accept `hpip`/`change-me`.
- Backend `pytest` with that isolated URL: **136 passed**. Ruff clean. Frontend `tsc` passed. Frontend lint is not configured. Frontend production build did not complete in the verification window.
- Status remains **not yet owner-accepted**. Live DHIS2 verification is still pending.

## 2026-09-11 — Phase 2 data foundation

Implemented DHIS2 aggregate/Event Analytics/Tracker connectors, geography and population engines, deterministic indicator calculation, and a separate data-quality engine. No dashboard screens, AI runtime, publishing, maps, or live DHIS2 connection.

- Added versioned source/event mappings, raw snapshot persistence with supersession, sync-job orchestration, and freshness snapshots.
- Added FY population-year configuration, period adjustment for population-derived denominators only, and facility catchment history.
- Added constrained formula engine, RAG/BLUE classification, reproducible calculation runs, and quality flags with evidence.
- Automated tests: `pytest` 95 passed; `ruff` clean. Live DHIS2 verification pending authorised endpoint configuration and credentials.

## 2026-09-11 — Phase 1 foundations

Implemented architecture, domain/database model, and authentication/authorisation. No DHIS2 connection, calculation engine, dashboard screens, AI runtime, or publishing.

- Added FastAPI backend, Next.js context shell, Alembic baseline, synthetic development users, and server-side geography/programme/action checks.
- Documented stack in `docs/architecture/ADR-001-stack.md`.
- Automated tests cover migrations, landing scope, permission denials, MPDSR separation, audit logging, health/readiness, and environment validation (`pytest`: 35 passed; `ruff`: clean).

## 2026-09-11 — Initial context ingestion

Project context imported from canonical Markdown, detailed Word blueprint and approved visual reference set.

- Reviewed the canonical handoff, detailed blueprint, and five 1672×941 reference images.
- Added project-context navigation, analytical rules, DHIS2 notes, visual contract, decision register, open-item register, roadmap state, and repository working instructions.
- No application implementation, production connection, credential request, fake UID, production population value, or unapproved threshold was created.

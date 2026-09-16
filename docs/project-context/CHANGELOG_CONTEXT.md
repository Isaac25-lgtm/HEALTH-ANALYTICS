# Context Changelog

## 2026-09-15 — Independent audit corrections (third pass)

An independent rerun reproduced defects that the second-pass handoff had reported as closed. This
pass corrects those defects without deploying, contacting DHIS2/Neon/Render, importing population,
or activating boundaries.

- **Search scope:** geography path prefixes now escape SQL `LIKE` metacharacters. A grant whose
  path contains `_` or `%` cannot match a sibling path. The regression constructs `/UG/A_B` and
  `/UG/AXB` and proves that only the first subtree is returned.
- **National root:** reference bootstrap refuses a second active country root. System-administrator
  landing independently selects the active root code `UG` with no parent instead of an arbitrary
  country row.
- **Playwright lifecycle:** the acceptance gate now builds first, then owns the disposable API,
  production Next server and Playwright runner as direct child processes. This avoids Playwright's
  shell-based Windows `taskkill` path, which returned Access Denied under the audit account. The
  gate has separate post-summary, pre-summary inactivity and overall timeouts.
- **Process proof:** failure of `Get-CimInstance` no longer becomes an empty successful process
  table. Windows falls back to a before/after PID-and-start-time inventory of Node, Python and
  browser processes; failure of both mechanisms fails the gate. Linux/macOS retain parent-tree
  enumeration. The gate also compares Git state before and after the run, so ordinary runs cannot
  write screenshots or other files unnoticed. A pre-existing dirty tree is permitted; the status
  lines and (since the review below) a content fingerprint must be identical afterwards.

Verification on the changed surfaces: Ruff clean; focused backend suite **77 passed**; isolated
PostgreSQL 18 bootstrap suite **4 passed**; TypeScript and ESLint clean; full `npm run e2e:gate`
**24 passed, 0 skipped, 0 flaky**, Playwright exited 0.1 seconds after its summary, both owned
services stopped, 100 created processes were observed through the restricted-account fallback,
none survived, and ports 3000/8010 were free. A deliberate one-second overall timeout exited 1,
stopped both services, left no observed process and freed both ports. The final full backend run was
**770 passed, 32 skipped**; the skips were the 30 PostgreSQL-only and two Redis tests, with the
changed PostgreSQL bootstrap surface separately proven as above.

**Review of the third pass (same day, second agent).** The four corrections were kept. Review of the
gate found and corrected three further gate defects:

- The descendant walk did not guard against cycles in the Windows parent-PID graph (PID reuse). A
  deliberate 30-second timeout reproduced it: the sampler threw `RangeError: Invalid array length`
  from a timer callback and crashed the gate before cleanup and summary (exit 1; no process was
  left). The walk now visits each PID once and rejects a child created before its supposed parent,
  and a sampling error is recorded as a gate failure instead of crashing the gate.
- The before/after Git comparison used status lines only, so a run that rewrote an already-modified
  file would pass. It now also compares a SHA-256 fingerprint of the binary diff against `HEAD` and
  untracked file bytes (the screenshot directory is excluded only for an explicit evidence refresh).
- The production build had no bound and was not sampled. It is now an owned child bounded by
  `E2E_BUILD_TIMEOUT_SECONDS` (900). In parent-tree mode, survivors proven to descend from the
  gate's own children are terminated after the failure is recorded; the baseline-delta fallback
  never terminates anything.

Independent verification of the final working tree (not committed):

| Gate | Result |
|---|---|
| Ruff (`app tests scripts alembic`) | clean |
| Focused backend (`test_search.py`, `test_reference_bootstrap.py`, `test_phase12_corrections.py`) | **77 passed** |
| Full backend, SQLite | **770 passed, 32 skipped** (30 PostgreSQL-only, 2 Redis), 0 failed |
| Full backend, PostgreSQL 18 disposable cluster on 55432 | **800 passed, 2 skipped** (Redis), 0 failed |
| TypeScript / ESLint / Vitest | clean / clean / **87 passed** |
| `npm run e2e` (final code) | **24 passed, 0 skipped, 0 flaky**; exit 0 by itself, 0 s from summary to exit; parent-tree mode, 114 processes observed, 0 alive; owned services stopped; ports 3000/8010 free; tree unchanged by the run |
| Failure path, `E2E_OVERALL_TIMEOUT_SECONDS=30` (browsers running, 17 tests completed) | exit 1; Playwright stopped by SIGTERM; services stopped; 95 processes observed, 0 alive; ports free. The survivor-termination branch was not exercised because no process survived. |

Before the first run, `CodexSandboxOffline` had again written `frontend/.next` (subfolders),
`frontend/test-results` and `backend/e2e_hpip.sqlite`; the build guard failed the gate (exit 1).
They were moved, not deleted, to `.build-quarantine/20260915-third-pass/`.

## 2026-09-16 — Acceptance-gate corrections (fourth pass)

Bounded corrections to `npm run e2e` only. No application behaviour, deployment, push, or external
service was touched. Lifecycle logic moved from `scripts/e2e-gate.mjs` into `scripts/e2e-gate-lib.mjs`
so it can be tested deterministically; `scripts/e2e-gate-lib.test.mjs` runs under `npm test`.

- **Root PID-reuse safety:** every owned process (build, API, Next server, Playwright) is identified
  by PID **and** creation time, captured immediately after spawning and accepted only when the row
  was created no earlier than the spawn and the process is still running after the query. Descendants
  are attributed only through a live root whose current row matches that identity, so an exited or
  reused root PID discovers nothing. Survivors are matched again by PID and creation time in a fresh
  query before termination, so ancestry inferred from a reused PID can never be terminated.
- **Spawn failures:** the `error` handler is attached at spawn; a missing executable, access-denied
  or other spawn error becomes an ordinary gate failure carried in the owned process outcome. The
  gate still performs bounded cleanup, prints the JSON summary and exits non-zero.
- **Bounded enumeration:** every process-table query (baseline, sampling, final verification and
  survivor revalidation) is bounded by `E2E_PROCESS_QUERY_TIMEOUT_MS` (20 s). On timeout only the
  gate's own lister child is stopped, enumeration is recorded unavailable and the gate fails closed
  without falling back to another mode. An in-flight sample is awaited before the summary.
- **Also found in review:** Playwright's output listener was attached after the identity query, so a
  summary printed in that window was missed; it is now attached at spawn.
- **Documentation:** the obsolete "requires a clean tree" claim is corrected. The gate permits a
  pre-existing dirty tree and requires identical status lines and content fingerprints after the run.

Verification (Windows workstation, parent-tree mode; working tree uncommitted by owner instruction):

| Gate | Result |
|---|---|
| `node --check` on both gate scripts | clean |
| TypeScript / ESLint | clean / clean |
| `npm test` (Vitest, including 16 new gate tests) | **103 passed** |
| `npm run e2e` | **24 passed, 0 skipped, 0 flaky**; exit 0 by itself, 0 s from summary to exit; all four owned identities verified; 106 processes observed, 0 alive; ports 3000/8010 free; tree unchanged |
| `E2E_OVERALL_TIMEOUT_SECONDS=30` (browsers active, 18 tests completed before the bound) | exit 1; Playwright stopped by SIGTERM; both services stopped; 0 survivors; ports free |
| `HPIP_PYTHON` set to a nonexistent executable | exit 1; `e2e-api could not be started (spawn failed: ENOENT…)`; build stopped; 0 survivors; ports free |
| `E2E_PROCESS_QUERY_TIMEOUT_MS=50` (every real query exceeds the bound) | exit 1; `process_check_mode: unavailable`; failure `process enumeration was unavailable before the run: process enumeration timed out after 50ms`; no lister left running; ports free |
| Synthetic root-PID-reuse, child-PID-reuse, cycle and creation-ordering cases | no unrelated process classified or terminated |
| Survivor termination with a real detached child | observed through the verified root, reported alive, terminated after revalidation, confirmed dead |
| `git diff --check` | clean |

### Follow-up correction to the fourth-pass gate

Independent reproduction rejected the one-run `103 passed` claim above: the complete suite produced
**102 passed, 1 failed** while the nominal clean gate reported five surviving processes. The isolated
gate file passed, identifying a concurrency-dependent false positive rather than a stable closure.
Restricted-Windows baseline-delta mode cannot distinguish gate-created processes from unrelated
Vitest workers created after its baseline.

The correction makes the initial process inventory a hard prerequisite: if it is unavailable, the
gate sets `execution_started: false` and launches no build, API, web server or browser. Survivor
verification now performs bounded repeated queries for up to `E2E_PROCESS_SETTLE_TIMEOUT_MS`
(default 5 s) and records diagnostic PID, creation time, attribution root and process kind for any
persistent survivor. Gate integration tests run without parallel test-file workers, while preserving
the real detached-child detection and termination case. Identity capture now uses the process
table's declared timestamp resolution (Windows 1 ms; Unix `ps lstart` 1 s), replacing the previous
two-second allowance.

Verification after correction: Node syntax, TypeScript and ESLint are clean; the gate file is
**18 passed**; the complete frontend suite is **105 passed** in three consecutive runs. A real
entrypoint run with `E2E_PROCESS_QUERY_TIMEOUT_MS=1` exited 1 with `execution_started: false`, no
owned processes, no report-freshness error and ports 3000/8010 free. No backend file was changed by
this follow-up.

Full Playwright was then run under the checkout-owning account on 2026-09-16: `npm run e2e`
**24 passed, 0 skipped, 0 flaky**, `execution_started: true`, parent-tree mode, Playwright exited 0
by itself 0.1 s after its summary, all four owned identities verified, 102 processes observed with
none alive after one settle check, both owned services stopped, ports 3000/8010 free, and the
working tree's status and content fingerprint unchanged by the run.

## 2026-09-15 — Corrective pre-UAT implementation (second pass)

Follows the audit of `fbf8a3a`. **Nothing was deployed or pushed, no remote was created, live DHIS2, Neon, Render and external AI providers were not contacted, no population was imported, no boundary was activated, no user or credential was created, and nothing is owner-accepted.** Details are in `DEFECT_MATRIX.md` ("second pass").

- **Bootstrap drift:** every bootstrap-owned field is compared before any write; any conflict writes nothing and exits 3 (29 mutations on SQLite and PostgreSQL).
- **Boundary governance:** district/city `source_features = 146`, `reconciliation_matched = 3`, `reconciliation_unmatched = 143`, `non_production_candidates = 3` (Kitgum, Pader, Soroti), `production_resolved = 0`, `production_unresolved = 146`; sub-county `source_features = 2,190`, `production_unresolved = 2,190`. Activation now needs recorded hierarchy, mapping-decision and effective-date approval references; `--effective-date-verified` alone is not approval.
- **Playwright shutdown:** the earlier entry below says the runner "exited"; the audit could not reproduce a clean return, and that statement is withdrawn. The cause was the `next start` child inheriting Playwright's stdio. `npm run e2e:gate` now proves exit 0 within a bound, free ports, no surviving descendants and a clean tree. (Superseded on 2026-09-16: the gate permits a pre-existing dirty tree and requires the status lines and content fingerprint to be identical after the run; see `LOCAL_DEVELOPMENT.md`.)
- **Visual contract:** icons, grouped navigation, alerts/profile area, authorised search, KPI and panel anatomy, with DOM-contract assertions.

## 2026-09-15 — Corrective pre-UAT implementation and final audit

Corrects eight code-controlled blockers found after the 2026-09-14 pass. **Nothing was deployed or pushed, no Neon or Render account was contacted, live DHIS2 was not contacted, no population was approved or imported into a production database, no boundary was activated, no real user was created, and nothing is owner-accepted.** Details per item are in `DEFECT_MATRIX.md` ("Corrective pre-UAT pass").

- **A. Fresh database:** `scripts/bootstrap_reference_data.py` creates the approved reference configuration after migrations, so empty → head → bootstrap → first administrator → login now works (proven on SQLite and PostgreSQL 18.1).
- **B/C. Proxy and Blueprint:** the build-time rewrite is replaced by a runtime `/api` route. `render.yaml` now has a private API service, `type: keyvalue`, a Blueprint-defined non-secret group, secrets declared once and copied with `envVarKey`, migrations then bootstrap before deploy, and no inert DHIS2 cron. Render's own Blueprint validation was **not** run.
- **D. Neon URLs:** plain `postgresql://` URLs are normalised to psycopg 3, TLS is validated for both URLs, and Alembic uses the runtime connection arguments with NullPool.
- **E. Purge failures:** failed policies now fail the execution and retry, undeleted files keep their path and job, and the lease is renewed and checked inside every batch.
- **F. MPDSR:** there is no free-text cause field. Causes are taxonomy codes only, and with no taxonomy configured they are dropped. Dates and event types have strict formats.
- **G. Population staging:** `production_unresolved` = 146/146 while the hierarchy is unapproved (143 reconciliation-unmatched, 3 non-production candidates). Migration `0012_population_staging_identity` makes staging idempotent, and there is a governed review transition. Reports were regenerated.
- **H. Visual acceptance:** information-dense 16:9 compositions per screen and workspace, built from shared panels, with Playwright visual gates. Screenshots are in `docs/evidence/screenshots/`.

Verification on 2026-09-15 (Windows workstation):

| Gate | Command | Result |
|---|---|---|
| Backend lint | `python -m ruff check app tests scripts alembic` | clean |
| Backend, PostgreSQL 18.1 disposable cluster (port 55432) | `HPIP_POSTGRES_TEST_URL=postgresql+psycopg://hpip@127.0.0.1:55432/postgres python -m pytest -q -rs -p no:cacheprovider --basetemp C:/hpt/pg` | **749 passed, 2 skipped** (Redis) in 532 s |
| Backend, SQLite | `python -m pytest -q -rs -p no:cacheprovider --basetemp C:/hpt/sq` | **722 passed, 29 skipped** (27 PostgreSQL-only, 2 Redis) in 489 s |
| Frontend typecheck / lint / unit | `npx tsc --noEmit`, `npx eslint .`, `npx vitest run` | 0 errors / 0 errors / **87 passed** |
| Production build (real repository, no backend address) | `npm run build` | exit 0 |
| Proxy build verification | `node scripts/verify-proxy-build.mjs` | passed: 0 rewrites, 0 of 28 client chunks with a backend address, `hpip-api:10000` → 502 with 0 localhost requests, unset → 500 |
| End-to-end | `npx playwright test` then `node scripts/assert-no-skips.mjs playwright-report/results.json` | **22 passed, 0 skipped** in 93 s; ports 3000/8010 free (the claim that the runner exited by itself was not reproduced by the audit; see the second-pass entry) |

Test-environment note: with a long pytest `--basetemp` under the scratchpad directory, six export tests failed because the generated artifact paths exceeded the Windows path limit. They pass with the short basetemp above. That was an environment limitation, not an application failure; Render runs Linux and stores export bytes in the database. One stale assertion (the removed `NEXT_PUBLIC_API_BASE_URL` fallback) was updated to the new same-origin contract.

Not executed locally: Render Blueprint validation (no Render access authorised), queued export generation over real Redis/Celery (no Redis on the workstation; the Playwright export uses `EXPORT_EAGER=true`), Docker image builds and Compose (Docker not installed), any deployment, and live DHIS2.

## 2026-09-14 — Pre-DHIS2 productionisation (Render + Neon UAT preparation)

This entry prepares UAT on Render with Neon PostgreSQL for about 100 light users (D-042 to D-049). **Nothing was deployed, no Neon database was connected, live DHIS2 was not contacted, and nothing is owner-accepted.** Work is committed to a local Git repository on `master` with no remote.

- Git baseline with `.gitignore` excluding secrets, clusters, build output and the large owner sources (see `SOURCE_ARTIFACT_MANIFEST.md`).
- The Alembic head is `0011_population_import_staging`:
  - `0009_retention_artifacts`: artifact storage and expiry, `export_artifacts`, `maintenance_runs`, `maintenance_locks`, retention indexes.
  - `0010_denominator_provenance`.
  - `0011_population_import_staging`.
  - 0001–0008 are unchanged.
  - The 0009 revision id was shortened from 35 characters before any deployment, because PostgreSQL's `alembic_version.version_num` is VARCHAR(32). A static test now guards this.
- Retention (D-043): raw aggregates 7 days, MPDSR events and their UIDs 24 hours, export files 24 hours, export job metadata 90 days, snapshots 36 months, audit 24 months. One purge service is shared by the CLI, the Celery maintenance task and the Render cron. It uses per-policy leases and batches, is idempotent, and its dry run writes nothing.
- MPDSR event minimisation uses a whitelist. Cause analysis and timeliness remain disabled or unverified; no date mappings were invented.
- Export artifacts go through `artifact_store` (filesystem or database). Expired files return 410 `artifact_expired`; the job record and checksum survive the file.
- Population: a central `resolve_target_denominator` applies D-045 period rules (2024–2030 seeded) and records provenance with each value. Sub-county values are reported as "Population denominator unavailable". Workbook staging preserves all 146 rows. Reconciliation reports are in `docs/reconciliation/`: 3 of 146 units match the synthetic seed; no production import was performed.
- GeoJSON validation and reconciliation reports record the boundary effective date as "not yet verified". Activation refuses without a verified date.
- Neon readiness: small pools, TLS required, a direct `MIGRATION_DATABASE_URL`, and fail-closed production validation for the API and worker. `render.yaml` defines web, API, one worker, Key Value, a purge cron, and an inert six-hourly DHIS2 refresh; there is no Render PostgreSQL.
- The browser uses a same-origin `/api` proxy, so session and CSRF cookies are first-party.
- Frontend:
  - Specialised workspaces (quality console, export history, administration panels) and prototype visual tokens. No calculations run in the browser.
  - The login page has a blank username.
  - `scripts/create_initial_admin.py` has no defaults.
- The DHIS2 discovery and refresh commands are prepared and refuse or stay inert while `DHIS2_ENABLED=false`.

Verification on 2026-09-14 (Windows workstation):

- Backend Ruff: clean.
- Backend pytest, full suite with `HPIP_POSTGRES_TEST_URL` set to a disposable PostgreSQL 18.1 cluster on port 55432: **544 passed, 2 skipped** in 763 s. The two skips are `test_redis_integration.py`, because no disposable Redis was available. Ports 5432 and 5433 were not touched.
- An earlier full run without PostgreSQL reported 2 failures, 521 passed and 20 skipped (18 PostgreSQL, 2 Redis). Both failures were assertions that predated this phase's intentional changes (the same-origin API default, and the new boundary reconciliation CLI). They were updated to the new contract, not removed.
- The first PostgreSQL run exposed the over-long 0009 revision id and a stale patch target in the PostgreSQL export-queue test. Both were fixed before the clean run.
- New PostgreSQL coverage: the 0008→0009 backfill, the downgrade and re-upgrade to head, and purge-lease exclusivity with six concurrent connections for both fresh and stale leases.
- Frontend: `tsc` 0 errors, ESLint 0, Vitest 35 passed, `npm run build` exit 0 in the real repository.
- Playwright against the final code: **12 passed** in 157 s with the system Chrome, with `assert-no-skips` passing. The runner exited by itself, and ports 3000 and 8010 were free afterwards.
- Not executed locally: Docker Compose and container builds (Docker not installed), real Redis and Celery-over-Redis (CI only), any Render or Neon deployment, and live DHIS2.

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

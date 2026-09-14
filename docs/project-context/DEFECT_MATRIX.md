# Corrective defect matrix — 2026-09-12

Status is evidence-based. Passing prior tests did not close these defects.

| Requirement | Previous failure | Root cause | Files changed | Regression | Final result |
|---|---|---|---|---|---|
| Successful analytical request must persist identifiers | Dashboard returned a run UUID absent in a new session | `get_db` closed without commit; tests hid this with a shared session | `app/db/session.py`, `app/api/deps.py`, `app/services/analysis.py`, `app/services/dashboard.py`, `app/api/routes/dashboard.py` | `test_dashboard_snapshot_exists_in_a_new_session` uses real `get_db` + a second session | Snapshot and values exist after commit |
| Failed generation must not leave a completed snapshot | Partial rows could flush then roll back inconsistently | No explicit write unit of work | Same + `test_failed_dashboard_leaves_no_completed_snapshot` | Forced persist failure | No completed snapshot row |
| Exports/AI must use the displayed snapshot | Endpoints silently recalculated | `create_export`/`run_ai_task` called `build_dashboard` | `publishing.py`, `ai_gateway.py`, export/AI routes, frontend API | `test_export_and_ai_require_matching_snapshot`, `test_historical_export_does_not_follow_later_raw_changes` | 422/409 on mismatch; historical export unchanged |
| Formula version for the requested period | Only `is_current` versions were used | `run_calculation` ignored validity dates | `calculation.py` | `test_historical_formula_version_is_selected` | Period-valid version selected |
| Safe hierarchy prefix queries | `path.startswith` became SQL `LIKE` wildcards | `_` and `%` in codes | `geography.py` | `test_like_wildcard_codes_do_not_expand_subtrees` | Underscore/percent codes isolated |
| Effective-date org-unit mappings | Latest/any mapping won | Date ignored; overlaps allowed | `geography.py`, `sync.py` | date-aware + overlap tests | Historical remap preserved |
| MPDSR event scope | Any tracker event with the same `event_type` counted | No programme/program UID filter | `mpdsr_events.py`, `calculation.py`, `modules.py` | `test_mpdsr_ignores_foreign_program_events` | Foreign program events excluded |
| Quality lifecycle | Flags were list/get only | No acknowledge/resolve/reopen/suppress | `quality.py` | Route contract added | Admin-permissioned mutations |
| Production CORS | Localhost always allowed | Hard-coded origins | `config.py`, `main.py`, `security.py` | `test_production_cors_does_not_auto_permit_localhost` | Localhost stripped outside dev/test |
| Gold-standard tests | Numerators derived from expected percentages | Tautological fixture loader | `acholi_gold_standard.json`, phase 3/7 tests | Independent `VERIFIED FIXTURE` sources | Same expected outputs from explicit counts |
| Alembic head | Schema corrections would have rewritten 0001–0005 | Missing forward revision | `0006_corrective_snapshots.py` | head + 0005→0006 tests | Forward-only 0006 |
| Facility population race | Two connections could both mark current | Prior row lock only when a current row existed | `population.py`, `0006` login index, concurrency test | `test_postgres_two_connection_facility_population_approval` | Exactly one current approved row |
| Exports generated in the API request | No queued/worker boundary | `create_export` wrote files immediately | `publishing.py`, workers, frontend poll | `test_export_stays_queued_until_worker_runs` | Queued until worker; eager only when configured |
| Maps used first object value / SVG-only | `Object.values(...)[0]` and no production map library | Generic dashboard map | `AdaptiveMap.tsx`, `MapLibreCanvas.tsx` | Playwright selector/snapshot test plus typecheck/build | Selected indicator colours MapLibre features |

## Material amendment — 2026-09-13

Results are from tests executed on 2026-09-13 (SQLite plus the disposable PostgreSQL 18 cluster on port 55432). Passing tests do not constitute owner acceptance.

| § | Requirement | Previous failure | Root cause | Main files changed | Regression tests | Result |
|---|---|---|---|---|---|---|
| 1 | Analytical execution must not happen on GET | `GET /analytics/dashboard` and `GET /analytics/modules/*` created runs and snapshots; `GET /exports/jobs/{id}/file` wrote audit rows | Mutations behind safe methods (CSRF-exempt) | `api/routes/dashboard.py`, `modules.py`, `analysis_snapshots.py`, `exports.py`, `services/analysis.py`, migration 0007, frontend `api.ts`, `DashboardView.tsx`, pages | `test_amendment_execution_contract.py` (every GET route leaves the DB byte-identical; CSRF 403; request-key reuse adds no runs; 409 conflict; per-user keys; owner-only snapshot; permissions re-checked; AI omitted-module bypass closed; IDs in a new session; failed execution leaves no runs/values/flags/snapshot), Vitest `execution.test.tsx`, Playwright "POST once, refresh re-opens snapshot" | Passed |
| 2 | Workbook identity and N.5 regressions | Acholi gold fixture used 1,000,000 population and back-calculated counts; §14.1 PMR/MMR untested | No verified population source | `services/population_workbook.py`, `scripts/import_population_workbook.py` | `test_population_workbook.py` (checksum, 146/135/11, 1,022 cells, totals, N.5 values, file unchanged), `test_amendment_acholi_n5_gold.py` (ANC1 97.4/95.4, institutional delivery 71.4/67.6, PMR 20.4, MMR 80.1 from district/city populations) | Passed |
| 3 | Reviewed crosswalk, no fuzzy matching | No alias mechanism | — | `population_workbook.py`, `PopulationSourceAlias` | `test_population_workbook.py` (exact/unmatched/type mismatch/ambiguous/duplicate target/pending/rejected/approved; second reviewer; audit; drafts only; national total opt-in; district+city children sum) | Passed |
| 4 | No invented sub-annual population year | FY rules silently applied to quarters and months | Rule lookup by parent FY | `services/population.py`, `models`, migration 0007, `seed.py` | `test_amendment_population.py`, updated quarter tests | Passed; rule recorded as open |
| 5 | Facility catchment is facility-only | Child sums could include facility entries | Child-sum helper mixed sources | `services/population.py` | `test_amendment_population.py` | Passed |
| 6 | Verified zero vs unknown MPDSR | Missing events counted as zero | No coverage evidence | `services/event_coverage.py`, `calculation.py`, `sync.py` | `test_amendment_mpdsr_coverage.py`, `test_amendment_sync_freshness.py` (window through extraction verifies; period-only window does not) | Passed |
| 7 | One common numerator/denominator scope | Parent numerator combined with child denominator | Components resolved independently | `calculation.py`, `quality.py` | `test_amendment_aggregation_scope.py` | Passed |
| 8 | District/city peers; no district+facility mix | Cities treated as a different level; nested double counting possible | Level rank comparison | `domain/enums.py`, `services/geography.py`, `calculation.py`, `quality.py` | `test_amendment_aggregation_scope.py` | Passed |
| 9 | Direction-aware findings and rankings | Rankings sorted raw values; AI called any increase an improvement | No interpretation layer | `domain/interpretation.py`, `modules.py`, `dashboard.py`, `ai_gateway.py`, `KpiCard.tsx` | `test_amendment_interpretation.py` (every mode, BLUE/missing, precision, ranking exclusions, unsafe indicators, API ranking) | Passed |
| 10 | Governed MPDSR causes | Cause counts exposed below region and without suppression | No disclosure policy | `modules.py`, `config.py` | `test_amendment_mpdsr_causes.py` | Passed |
| 11 | Blame/causation protection | Narrow keyword list; free-text provider output | — | `evidence.py`, `ai_gateway.py`, `providers.py` | `test_amendment_ai_safety.py` (all listed phrases via API, unsafe/invalid provider output falls back, valid statements accepted) | Passed |
| 12 | Freshness ordering | Freshness written before `finished_at`; first observation used | Call order in sync runners | `services/sync.py`, `routes/sync.py`, `quality.py` | `test_amendment_sync_freshness.py` | Passed |
| 13 | Map cohort | Client joined a separately fetched layer at a client-computed `as_of`; district shapes could stand in for regions | Map not tied to the snapshot | `services/geometry.py`, `dashboard.py`, `analysis_snapshots.py`, `AdaptiveMap.tsx`, `MapLibreCanvas.tsx` | `test_amendment_map_cohort.py` | Passed |
| 14 | Prototype blacklist | — | — | `UI_VISUAL_CONTRACT.md`; client-side value sorting removed | Review; no Google Fonts in `src` | Documented |
| 15 | Export completeness and labels | Blank governance columns; PPTX truncated to the first rows; mismatched labels | Writers read sparse evidence | `domain/exports.py`, `publishing.py`, `routes/exports.py`, `dashboard.py` | `test_amendment_exports.py`, `test_phase6_publishing.py` | Passed |
| — | Formula coverage matrix | EPI indicators reported as `approved` classification | Non-empty `{"mode": "unclassified"}` treated as approval | `test_formula_coverage.py`, `FORMULA_COVERAGE_MATRIX.json` | Full-matrix equality plus TBD assertion | Passed (24 approved, 30 TBD, 6 counts) |
| — | ESLint gate | 420 errors from generated `.next-gate` | Output directory not ignored | `eslint.config.mjs` | `npx eslint .` | 0 errors |

Remaining unverified or blocked items are listed in `OPEN_ITEMS.md`.

## Pre-DHIS2 productionisation — 2026-09-14

Results are from tests executed on 2026-09-14. SQLite unless marked PostgreSQL (disposable 18.1 cluster, port 55432). Passing tests are not owner acceptance.

| WP | Requirement | Defect or gap found | Main changes | Regression tests | Result |
|---|---|---|---|---|---|
| A | Safe Git baseline | No repository; 219 MB of boundary sources and a 10.7 MB .docx would have been committed | `.gitignore`, `SOURCE_ARTIFACT_MANIFEST.md`, `git init` | Staged-list and credential scan | Baseline `6800145`; no remote |
| C | Configurable retention | Raw aggregates, event UIDs and export files kept indefinitely | `domain/retention.py`, `services/purge.py`, migration 0009, `scripts/purge_expired.py`, Celery maintenance task | `test_retention_purge.py` (calendar months, dry run writes nothing, idempotency, batching, lease, stale lease, failure record, disabled) | Passed |
| D | Purge-safe provenance | Not previously proven | Denominator provenance (0010); snapshot/export reopen after purge | `test_snapshot_and_export_survive_the_deletion_of_their_raw_rows` | Passed |
| E | MPDSR minimisation | Blacklist of four names; nested and unmapped payloads could persist; flag `event_uid` never expired | `domain/mpdsr_minimisation.py` whitelist; purge clears flag UIDs | `test_mpdsr_minimisation.py` | Passed |
| F | Render-safe artifacts | Worker wrote to local disk the API could not read; expired downloads were bare 404s | `services/artifact_store.py` (`filesystem`/`database`), 410 `artifact_expired`, download re-checks permissions | `test_retention_purge.py`, `test_export_queue.py` | Passed |
| G/H | Workbook staging and reconciliation | 146 rows could not be preserved without an approved crosswalk | Migration 0011 staging, CLI `--stage`/`--write-reports` | `test_population_workbook.py`, reports in `docs/reconciliation/` | Passed; 143/146 production-unresolved |
| I/J/K | Central resolver and real populations | Sub-annual and calendar periods unresolved (now decided, D-045); resolution spread across calculation code | `resolve_target_denominator`, seeded 2024–2030 rules | `test_population_period_resolver.py` (Pader 2025 = 248,910 from fixture) | Passed |
| L | Prototype paths | None found in production code; no guard existed | Contract tests backend and frontend | `test_prototype_contract.py`, `prototype-contract.test.ts` | Passed |
| M | Boundary validation | No validation report; activation required an assumed date | `scripts/geojson_reconciliation.py`; `effective_date_verified` guard | `test_phase12_audit_fixes.py` | Passed; OBJECTID 1240 duplicate reported |
| N | Visual workspaces | All workspaces rendered one identical layout | `lib/workspaces.ts`, `QualityConsole`, `ExportHistory`, `AdministrationPanels`, `globals.css` tokens | `workspaces.test.tsx`, `e2e/workspaces.spec.ts` | Passed (Vitest 35; Playwright 12, no skips) |
| O | Development login | Username prefilled with `national.analyst`; no safe admin provisioning | Blank login; `scripts/create_initial_admin.py` | `test_admin_provisioning.py` | Passed |
| P | Neon readiness | No pool limits, TLS policy or direct migration URL | `db/session.py`, config validation, Alembic `migration_url` | `test_runtime_gates.py` | Passed |
| Q | Same-origin auth | CSRF cookie read via `document.cookie` would fail across Render hostnames | `/api` proxy (`BACKEND_INTERNAL_URL`), `render.yaml` | `test_deployment_config.py`, Playwright cookie test | Passed |
| S | DHIS2 discovery | Approximate hostname in docs; no enable switch | `DHIS2_ENABLED`/`SYNC_ENABLED`, inert discovery and refresh commands | `test_runtime_gates.py` | Passed; no network call made |
| P | Release on PostgreSQL | Revision id `0009_retention_and_artifact_storage` (35 characters) exceeded PostgreSQL `alembic_version.version_num` VARCHAR(32). SQLite does not enforce the length, so `alembic upgrade head` passed locally but would have failed at the Neon release | Revision renamed to `0009_retention_artifacts` before any deployment (0001–0008 untouched) | `test_revision_ids_fit_the_postgresql_version_column` (runs on SQLite), `test_postgres_0008_to_0009_backfills_artifact_expiry_and_downgrades` | Passed |
| C | Purge lease under contention | Lease exclusivity was only proven on SQLite | None needed | `test_postgres_purge_lease_admits_exactly_one_holder_under_contention` (6 threads, fresh and stale lease) | Passed |
| F | Stale test patch | PostgreSQL export-queue test still patched `export_jobs.os.replace`, which publication no longer uses | Patch `artifact_store.publish`; assertions unchanged | `test_postgres_export_queue_races_and_durable_failure` | Passed |
| T | Build hang | Another account (`CodexSandboxOffline`) rebuilt into `.next` during the session, re-triggering Next's infinite `EPERM` retry | Relocated output; `prebuild` fail-fast guard | Real-repository `npm run build` | exit 0 in 188 s |

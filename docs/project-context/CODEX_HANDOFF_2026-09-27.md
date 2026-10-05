# Codex handoff and review request — 2026-09-27

Written for: Codex (independent reviewer). Everything below was done by Claude Code between
2026-09-24 and 2026-09-27 under the owner's instructions. Treat every claim here as unverified until
you have checked it against the code, the tests and, where stated, the live local database.

The previous handoff is `docs/project-context/CODEX_HANDOFF_2026-09-20.md`. The last commit before
this work is `a69796d`. Read `AGENTS.md`, the canonical handoff
`ULTIMATE_IDE_HANDOFF_Uganda_Health_Performance_Intelligence_Platform.md`, `DECISION_REGISTER.md`
(D-057 to D-069 are new) and `OPEN_ITEMS.md` alongside this file.

---

## 1. What the owner asked for

1. Make the dashboard look and behave like the five reference PNGs in the repository root
   (`ChatGPT Image Sep 11 2026 ...png`) using live DHIS2 data only; no synthetic data at runtime.
2. Select any period: month, quarter, financial year, calendar year, or a custom range
   (e.g. Nov 2024 – Dec 2025), with history back to 2020.
3. Whole table cells coloured by status ("the entire box coloured"), a stronger palette, EPI bands.
4. A working district map with drill-down to sub-county and facility.
5. Downloads (Excel, PowerPoint, PDF, Word) that keep the colour coding.
6. A complete MPDSR section.
7. Fix KMC, resuscitation and malaria-vaccine problems, remove alert noise (the "99+" bell).
8. Now (this handoff): a full independent review — what is unfinished, skipped or inconsistent — and
   specifically **why the system loads slowly** (the owner has built similar systems that load
   instantly) and how to meet two new login requirements (section 9).

---

## 2. Repository state

| Item | State |
|---|---|
| `ca8cec7` | History, periods, colour, district map, speed. **Pushed** to `origin/main`. |
| `a74d0e0` | Colour-coded Excel/PowerPoint/PDF/Word downloads, MPDSR field discovery doc. **Pushed.** |
| Working tree | **Uncommitted**: 29 modified files and 7 new files (KMC, malaria, MPDSR wiring, sub-county/facility import, on-demand facility loading, aggregation rule change, further speed work). Run `git status` and `git diff` to see them. |

Remote: `https://github.com/Isaac25-lgtm/HEALTH-ANALYTICS`, local branch `master` pushed to `main`.

New uncommitted files:
`backend/app/services/facility_data.py`, `backend/scripts/apply_direct_indicator.py`,
`backend/scripts/apply_mpdsr_event_mappings.py`, `backend/scripts/import_live_subunits.py`,
`backend/tests/test_facility_on_demand.py`, `backend/tests/test_malaria_all_districts.py`,
`frontend/src/components/dashboard/FacilityDataBanner.tsx`.

---

## 3. Owner decisions recorded (see `DECISION_REGISTER.md`)

| ID | Decision | Status |
|---|---|---|
| D-057 | Keep aggregate DHIS2 history from July 2020 (`RAW_AGGREGATE_RETENTION_DAYS=3650`, `CALCULATION_SNAPSHOT_RETENTION_MONTHS=132` in the local `.env`). Months are the only stored source; longer periods are derived. | Applied |
| D-058 | Custom month ranges; population blended month by month. | Applied |
| D-059 | EPI bands: coverage green ≥90, amber 80–89.9, red <80; dropout green <10, red ≥10 (revision `v2-epi-bands`). | Applied |
| D-060 | District/city boundaries matched to the 146 live units; DHIS2 " District" suffix rule; aliases LUWEERO and SSEMBABULE. | Applied |
| D-061 | Boundary effective date 2020-07-01. | Applied |
| D-062 | Sub-counties attach directly to districts (DHIS2 level 4 skipped). | Applied |
| D-063 | MPDSR fields discovered read-only; candidates in `MPDSR_FIELD_CANDIDATES.md`. | Done |
| D-064 | Spike/drop checks compare only the preceding period of the same kind (defect fix). | Applied |
| D-065 | KMC uses DHIS2 indicator `DUFsfDA9YD2`. | Applied |
| D-066 | Successful resuscitation unchanged; >100% is a data-entry issue, stays BLUE. | Recorded |
| D-067 | Malaria vaccine considers every district (sum of reporting districts). | Applied |
| D-068 | MPDSR wired with the candidate fields; facility figures load on demand. | Applied |
| D-069 | MPDSR reported-death indicators sum reporting districts (same rule as D-067). | **Applied, awaiting explicit owner confirmation** |

---

## 4. Everything that changed, area by area

### 4.1 Monthly history (committed, `ca8cec7`)

- `backend/scripts/backfill_history.py`: resumable, idempotent month-by-month extraction for MNCH,
  EPI and MPDSR under mapping version `live-2026-09-21`. `ensure_mpdsr_wiring()` copies the four
  shared death keys (MATERNAL_DEATHS, NEWBORN_DEATHS, FRESH_SB, MACERATED_SB) from MNCH to MPDSR with
  an audit row. Result on the live DB: 220/220 jobs succeeded, months 202007–202608.
- Live raw rows at the time: EPI ≈199.9k, MNCH ≈181.6k, MPDSR ≈23.9k.

### 4.2 Periods and roll-ups (committed)

- `backend/app/domain/periods.py`: custom range keys `YYYYMM..YYYYMM` (max 72 months),
  `range_key`, `trend_window`, range handling in `parse_period` and `previous_period`.
  **Uncommitted:** `parse_period` is now `@lru_cache(maxsize=8192)` (PeriodSpec is frozen).
- `backend/app/integrations/dhis2/periods.py`: ranges are never sent to DHIS2 (translated to their
  months). **Uncommitted:** `covering_internal_period` now compares period *boundaries*, not labels,
  because DHIS2 `2025Q3` was rejected for `FY2025/26Q1`.
- `backend/app/services/period_rollup.py` (new): `ensure_period_rollups()` materialises FY, quarter,
  year and range rows as `sum_of_months` with component row IDs, only for programmes whose every
  month is extracted; freshness check compares latest month extraction to latest derivation.
  `_latest_derivation` uses one SQL `max()`. **Uncommitted:** `_summable_keys` never sums a key
  currently bound to a DHIS2 *indicator*.
- `backend/app/services/calculation.py` `prepare_calculation_batch` calls the roll-up in a
  savepoint first.
- `backend/app/services/population.py`: `_range_target_denominator` blends population month by
  month; unavailable if any month lacks an approved population.
- Frontend: `frontend/src/lib/periods.ts`, `frontend/src/components/dashboard/PeriodPicker.tsx`,
  `DashboardFrame.tsx` filter strip.

### 4.3 EPI bands and indicator revisions (committed)

- `backend/app/domain/indicator_catalog.py`: `indicator_revisions()` returns governed later versions
  built from the v1 base plus overrides. `backend/app/services/reference_bootstrap.py` creates each
  once and retires the previous current version.
- Revisions now defined: `v2-epi-bands` (24 coverage + 2 dropout), **uncommitted**
  `v3-malaria-all-districts` (5) and `v2-mpdsr-reporting-districts` (10). All were applied to the live
  DB with `python scripts/bootstrap_reference_data.py`.
- All formula versions remain undated; they resolve only under the UAT `development_default`
  policy (D-056). This is not production approval.

### 4.4 Visual changes (committed)

`frontend/src/app/globals.css` (heat tokens, whole-cell `td.cell`, KPI card status edges, rank bars,
period picker, facility banner), `KpiCard.tsx`, `ScorecardPanels.tsx`, `AnalysisPanels.tsx`
(status-coloured ranking bars via CSS `scaleX` so no client-side `* 100`), `TrendChart.tsx`
(round ticks, readable period labels), `ProgrammePanels.tsx` (continuum formatting), `lib/status.ts`
("Needs attention", "%" suffix, `not_interpreted` hidden).

### 4.5 District boundaries and map (committed)

- `backend/app/services/geometry.py`: district-type units also indexed without the " District"
  suffix; explicit `--alias FEATURE=UNIT` in `scripts/import_geojson.py`; aliases recorded in the plan
  and audit. Simplified geometry cached by geometry ID; shapes deferred when only metadata is needed.
- Live import: 146/146 features, `valid_from=2020-07-01`, approval reference in `.env`
  (`BOUNDARY_DISTRICT_HIERARCHY_APPROVAL_REFERENCE`, value not reproduced here).
- National and regional screens evaluate the district/city cohort (`district_comparison` in
  `modules.evaluate_module(..., district_cohort=True)`); the map and ranking use it.
  `analysis_snapshots.py` map-features route uses it too.

### 4.6 Speed work

Committed in `ca8cec7`:
- `quality.py`: flags read in bulk per scan (`_prime_flag_cache`), spike check uses one query for
  the comparable period.
- `calculation.py`: **run reuse** — `_input_fingerprint()` hashes software version, unit,
  descendant hierarchy, period, programme and indicator set, selected formula versions, current
  source rows (id, checksum, value, flags) and content of the reference tables; stored in
  `calculation_runs.idempotency_key` (migration `0014_calculation_run_reuse`, applied live). Batch
  loads one programme and defers provenance JSON; lineage mapping IDs fetched in one query;
  population/period-rule/mapping lookups memoised per batch.

Uncommitted (after the 11k-unit facility import made national views slow again):
- `geography.descendants()`: batch path uses a path-sorted index (`bisect`) and caches each subtree.
- `calculation.py`: hierarchy digest cached per unit; `_child_cohort` visits only units that hold a
  row for (period, key); expected cohort cached; subtree ID sets cached; batch rows and events
  selected by a path subquery instead of an 11k-item `IN` list; MPDSR events indexed per unit and
  per-period cohort; **event-based (MPDSR) runs may now be reused within the same clock hour** when
  the event digest and the latest tracker job are unchanged.
- `modules.py`: `scan_quality` is skipped when the current run was reused (`REUSED_RUNS_KEY`).
- `quality.py`: all flags of the scanned period loaded once (`_prime_period_flags`); stale/spike
  rows selected by path subquery. The file was fully reformatted by `ruff format` (diff noise).
- `population.py`: cohort sums skip facilities.
- `mpdsr_events.py`: `mpdsr_scope()` resolves programme and approved program UIDs once.

Measured on the live DB (warm = a repeat of the same view; cold = first view after data or code
changes). Times are server-side `build_dashboard` only:

| View | Before this work | Now (warm) | Now (cold) |
|---|---|---|---|
| National ANC FY2025/26 | 196 s | ≈12 s | ≈24–40 s |
| National immunisation Jun 2025 | — | ≈14 s | ≈39 s |
| National MPDSR FY2025/26 | 274 s (profiled) | ≈20 s | ≈100 s |
| District facility first load (Kitgum FY) | n/a | — | ≈85 s incl. DHIS2 fetch |

These are still far from "loads seamlessly". See section 8.

### 4.7 Data-quality noise (committed)

`scripts/resolve_superseded_spike_flags.py` resolved 6,157 spike flags raised by the old
non-comparable comparison, with an audit row each; 332 genuine ones remain. About 3,194
`STALE_REPORTING` flags remain because every stored raw row older than 72 h is flagged; changing
that scope is an open owner decision, so the bell still shows a large count.

### 4.8 Downloads (committed, `a74d0e0`)

- `export_view.py` (presentation model: labels, heat colours, value formatting, period labels),
  `publishing_excel.py` (Scorecard, Units, Ranking, Trends with native chart, governance sheets),
  `publishing_pptx.py` (16:9, KPI cards, coloured tables, vector district map as freeforms,
  zero-based bar charts, trend chart), `publishing_documents.py` (PDF via reportlab with vector map;
  Word via python-docx without map), `publishing.py` dispatcher (`TEMPLATE_VERSION hpip-publish-2`).
- `export_jobs.py` attaches the snapshot's map features (simplified) under `_export_map_features`.
- Download route `?transport=blob`: octet-stream with `X-Export-Filename`, no `Content-Disposition`,
  because Chrome intercepted `*.pdf` attachments and gave the page an empty body.
- New dependencies in `backend/pyproject.toml`: `python-docx`, `reportlab`.

### 4.9 KMC (uncommitted code, live DB already changed)

- `scripts/apply_direct_indicator.py`: rebinds a key to a DHIS2 indicator and extracts it natively
  for UG, regions and districts for every month, FY, FY quarter and calendar year since July 2020.
  Ran for `KMC_PERCENT` → `DUFsfDA9YD2`; 11,045 old count rows retired (`is_current=false`);
  116 period jobs (25 FY-quarter jobs failed first, fixed by the boundary comparison, then resumed).
- `sync.py` `_run_aggregate`: DHIS2 indicators are also requested for country/region units
  (`_aggregate_level_uids`).

### 4.10 Malaria vaccine (uncommitted)

- `formula_spec.py`: new `child_coverage: "complete_cohort" | "reporting_units"`.
- `calculation.py`: `_child_cohort(..., allow_partial)` and `resolve_common_scope(..., allow_partial)`;
  result policy `children_reporting` with a "N of M units reported" reason.
- `KpiCard.tsx` shows "Sum of reporting districts".
- Live: national MV1 61.5%, MV4 13.3% (FY2025/26).

### 4.11 MPDSR (uncommitted code, live DB already changed)

- Read-only discovery of the four DHIS2 event programs (004, 020, 019, 017), documented in
  `MPDSR_FIELD_CANDIDATES.md`.
- `scripts/apply_mpdsr_event_mappings.py`: 8 `EventFieldMapping` rows (death date + each form's
  event date as notification or review date). Applied live.
- `sync.py`: tracker jobs iterate every mapped program UID; the reserved source `occurredAt` maps the
  event date. Only `event_type`, `death_date`, `notification_date`, `review_date` survive
  `mpdsr_minimisation.py` (verified on 5,000 stored events).
- First extraction rejected every event (facility org units were not yet imported). After the
  facility import: FY2025/26 44,223 events stored (2,332 s), FY2024/25 78,114 (6,249 s).
- `v2-mpdsr-reporting-districts` (D-069) for the 10 indicators built on reported deaths; before it,
  national reported deaths were "incomplete_children" because only 132 of 146 districts had a
  maternal-death row. Live national FY2025/26 now: perinatal reported deaths 23,789, maternal 976,
  maternal notification coverage 40.3%, maternal review coverage 94.0%, etc.

### 4.12 Sub-counties and facilities (uncommitted code, live DB already changed)

- Levels 4–6 fetched read-only district by district (DHIS2 2.41 paging was unreliable and the
  national facility list exceeded the client's response bound) into `.local/dhis2/org-units-l4-l6.json`.
- `scripts/import_live_subunits.py`: 2,206 sub-counties under their district, 8,789 facilities under
  their sub-county, 10,995 DHIS2 mappings, codes `NAME_UID`, facility level/ownership only when one
  DHIS2 group states it, 72 closed facilities inactive. Applied live.

### 4.13 On-demand facility figures (uncommitted)

- `facility_data.py`: `facility_data_status()` (months of the period not yet loaded; the two latest
  closed months re-checked after 24 h), `queue_facility_load()` (one `aggregate_facilities` sync job,
  never duplicated, nothing queued when DHIS2 extraction is off), `run_facility_job()` (own session),
  `prefetch_home_district()` (district-scoped users at sign-in).
- `sync.py`: job type `aggregate_facilities` → `_run_facility_aggregate()` expands the month span and
  requests the district's mapped facility UIDs.
- `dashboard.py`: district/sub-county/facility screens queue a load and return `facility_data`;
  the facility scorecard only calculates facilities with stored figures; ranking prefers an
  indicator that the compared units actually have values for.
- `routes/dashboard.py`: starts queued jobs as FastAPI background tasks after commit; new
  `GET /analytics/dashboard/facility-status`. `routes/auth.py`: prefetch after sign-in.
- Frontend: `FacilityDataBanner.tsx` polls every 5 s and re-runs the dashboard when ready;
  `ScorecardPanels.tsx` switches to the Facilities tab when rows arrive and hides population
  columns that no facility has (facilities have no approved catchment populations).
- Verified live: Pader Jun 2025 (1 month, 13 s) and Kitgum FY2025/26 (12 months, ≈85 s, 29 facilities).

### 4.14 Aggregation rule change (uncommitted, important to review)

`_child_cohort` used to reject a parent when descendants held rows at two aggregation classes
("mixed_levels"). With facility rows loaded beneath districts, national values would have vanished.
Now only the class nearest the parent is summed; deeper rows are ignored as components and never
stand in for a missing district. Two tests were rewritten accordingly
(`test_amendment_aggregation_scope.py`).

### 4.15 Tests changed

- Committed: `conftest.py` (pins boundary approvals and retention defaults so a local `.env` cannot
  leak into tests), `test_amendment_interpretation.py`, `test_amendment_map_cohort.py`,
  `test_calculation_engine.py`, `test_phase12_corrections.py`, `test_phase3_modules.py`,
  `test_migrations.py`, `test_postgres_migrations.py`, `test_reference_bootstrap.py`,
  `test_retention_purge.py`, `test_amendment_exports.py`, `test_phase6_publishing.py`, new
  `test_period_rollup.py`, `test_run_reuse.py`, `test_publishing_visuals.py`; frontend
  `execution`, `kpi`, `map-canvas`, `status` tests.
- Uncommitted: `test_amendment_aggregation_scope.py`, `test_amendment_map_cohort.py`,
  `test_mpdsr_privacy_formats.py`, `test_phase4_dashboard.py`, `test_run_reuse.py`, new
  `test_facility_on_demand.py`, `test_malaria_all_districts.py`.
- **Check whether each assertion change is a legitimate consequence of an owner decision or a test
  weakened to pass.**

Latest results (SQLite): backend 880 passed, 32 skipped; frontend vitest 111 passed; `tsc`, `eslint`
and `next build` clean. **Not run this pass:** the PostgreSQL suite (disposable cluster on port
55432) and the Playwright acceptance gate.

---

## 5. Live-database operations (local `hpip_live` on 127.0.0.1:5432)

Backups before each material change, in `C:\Users\USER\hpip-backups\`:
`hpip_live_20260924_221320_pre_boundaries.dump`, `hpip_live_20260925_065203_pre_kmc.dump`,
`hpip_live_20260925_101614_pre_facilities.dump`.

Operations performed: monthly backfill (220 jobs); migration 0014; reference bootstrap (revisions);
district boundary import; spike-flag resolution; KMC rebind and extraction; MPDSR event mappings and
two tracker extractions; sub-county/facility import; several on-demand facility loads (Pader, Kitgum).
DHIS2 was only ever read (GET). No credentials are stored in the repository; the DHIS2 password was
disclosed in chat earlier and must be rotated before any hosted use.

---

## 6. Known unfinished, skipped or questionable items (Claude's own list — verify it)

1. **Load time is still poor** (section 4.6 table). Every dashboard view runs calculations and
   writes a snapshot on the request path (`POST /analytics/dashboard/query`); nothing is
   precomputed. First views after any data or code change recalculate everything.
2. The period roll-up rebuilds a whole FY for **all** units and programmes whenever any month is
   extracted more recently than the last derivation, so every on-demand facility load triggers a
   national rebuild on the next request.
3. MPDSR events are subject to the 24-hour `MPDSR_EVENT_RETENTION_HOURS` purge. There is no scheduled
   tracker refresh; if purge runs, MPDSR counts become unavailable until re-extracted, and a
   national extraction took 40–100 minutes.
4. Hour-bounded reuse of MPDSR runs (4.6) is a judgement call; confirm it cannot serve a result whose
   event-coverage status has changed.
5. D-069 applied before explicit owner confirmation.
6. `STALE_REPORTING` noise (≈3,194 open flags) keeps the alert bell high.
7. Facility coverage percentages are unavailable (no approved catchment populations); facility map
   points are not imported (no approval); MPDSR cause patterns withheld (no approved taxonomy).
8. Formula versions are undated (UAT-only policy, D-056).
9. `_reference_state()` hashes the full content of eight reference tables once per request.
10. Browser screenshots of the national MPDSR, intrapartum and immunisation screens after the
    latest changes were not taken (stopped by the owner); downloads were not re-checked after the
    MPDSR/facility changes.
11. `quality.py` whole-file reformat mixes style changes with logic changes.
12. Docs: `CHANGELOG_CONTEXT.md` does not yet describe the latest MPDSR speed changes or the hour-bounded
    reuse; D-069 is in the register.
13. The uncommitted batch has not been committed or pushed.

---

## 7. How to run locally

- API: from `backend/`, `python -m uvicorn app.main:app --host 127.0.0.1 --port 8010` with
  `WEB_ORIGIN=http://localhost:3100`.
- Web: from `frontend/`, `npm run build` then `node node_modules/next/dist/bin/next start -p 3100`
  (production build; rebuild after frontend changes). Port 3000 belongs to an unrelated app — do not
  stop it.
- Tests: `python -m pytest -q -p no:cacheprovider tests` (≈13–14 min); `npx vitest run`;
  `npx tsc --noEmit -p .`; `npx eslint src`.
- The live runtime reads the gitignored root `.env`; never print or commit it.

---

## 8. The owner's performance concern

The owner reports that the system takes long to load, while systems they built before loaded
seamlessly. Please give a root-cause verdict, not just micro-optimisations. In particular assess:

- whether calculating on every view (write-on-read, snapshot per request, ~175 calculation runs for
  a national view with a 146-district cohort and 12 trend months) is the right architecture versus
  precomputing results after each extraction and serving reads from stored results;
- the cost of loading ~11k org units and hundreds of thousands of ORM objects per request;
- whether the frontend request flow (`DashboardView.tsx`: `router.replace` to add a request key,
  then `POST /analytics/dashboard/query`, then snapshot, then `getChildren`) adds avoidable round trips;
- what a realistic target is (sub-second or a few seconds) and the concrete steps to reach it without
  breaking the governance rules in `AGENTS.md` (traceability to source, formula version, population
  version and calculation run).

---

## 9. New owner requirements for sign-in

Current behaviour: `frontend/src/app/login/page.tsx` calls `login()` then `router.push("/")`; the
dashboard then shows "Loading authorised analytics…" while the first calculation runs, which can take
tens of seconds or more. The user's name appears only in the top bar after the dashboard loads.

Requested:
1. After signing in, the user should enter the dashboard only when it is ready to show, not land on
   an empty loading page.
2. During or immediately after sign-in, show the names the account is registered under (display
   name, and role/geography) so the person can confirm who they are signed in as.

Please propose how to implement both, consistent with the security model (DHIS2 password never
stored, CSRF, server-side permissions), and say what must change for (1) to be fast enough to be
worth waiting for.

---

## 10. What to return

1. A verdict table: each item in sections 4 and 6 marked **confirmed done**, **partly done**,
   **not done**, or **incorrectly done**, with file/line evidence.
2. Every inconsistency, defect or risk you find in the changed code (correctness first, then
   governance, security, performance), with file and line.
3. Anything claimed here that the code does not support.
4. Anything skipped that the owner asked for (section 1).
5. Your performance root-cause analysis and plan (section 8).
6. Your design for the sign-in requirements (section 9).
7. An overall assessment of how the execution was done.

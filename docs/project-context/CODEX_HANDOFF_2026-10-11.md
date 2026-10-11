# Handoff to Codex: 2026-10-11

You are picking up the Uganda Health Performance Intelligence Platform after a two-day pass by
Claude (10 and 11 October 2026). This file tells you what state things are in, what was changed and
why, which of those changes most need an independent check, and what is still open. It assumes you
have not seen the session.

The owner-facing account of the same work, with all measurements, is
[CLAUDE_HANDOFF_2026-10-11.md](CLAUDE_HANDOFF_2026-10-11.md). Read that too; this file does not
repeat its tables.

## 1. Read first

1. `AGENTS.md` (working rules; they override defaults).
2. [CLAUDE_HANDOFF_2026-10-11.md](CLAUDE_HANDOFF_2026-10-11.md).
3. `DECISION_REGISTER.md`, rows D-070 to D-075 (this pass).
4. `OPEN_ITEMS.md`, the section "Status after the 2026-10-11 pass".
5. Your own earlier records, for continuity: `CODEX_CORRECTIONS_2026-10-02.md`,
   `CODEX_FIX_HANDOFF_2026-10-05.md`, and Claude's `CLAUDE_AUDIT_2026-10-05.md`.

## 2. State right now (2026-10-11, 12:00 local)

| Item | State |
|---|---|
| Git | `master` = `origin/main` = `e932d47`, working tree clean. Previous commit `d07ac8f`. |
| Live local database `hpip_live` | Migration `0020_config_revision`. Backups in `C:\Users\USER\hpip-backups\`: `hpip_live_20261010_094850_pre_speed.dump`, `hpip_live_20261010_114919_pre_0019.dump`. |
| Local stack | API on 127.0.0.1:8010, web on localhost:3100 (production build). Started with `start-local.ps1`. |
| Local `.env` (gitignored, not secrets) | `DASHBOARD_PRECOMPUTE_ENABLED=true`, `DHIS2_REFRESH_SCHEDULE_ENABLED=true`, `DHIS2_TIMEOUT_SECONDS=120`, `SYNC_EXECUTION=eager`, `MPDSR_EVENT_RETENTION_HOURS=24`. |
| Aggregate data | Refreshed today 11:01 to 11:10 (latest three months and FY2026/27, three programmes, twelve jobs, all succeeded). |
| MPDSR events | **Expired.** No retained events. The last successful Tracker job finished 2026-10-10 10:34 (two financial years, 45,582 events). |
| Tracker job in progress | Started by the API's own scheduler today at 11:10:50, window FY2024/25 to FY2026/27. Still `running` at 12:00 with nothing committed. Outcome unknown. See section 5, item 1. |
| Stale job rows | `aggregate`, `queued`, created 2026-09-24. `aggregate_facilities`, `running`, created 2026-10-10 16:22 (interrupted by a shutdown). Neither was touched. |
| Open quality flags | MISSING_CAUSE 17,314; POSSIBLE_DUPLICATE_EVENT 6,857; REVIEW_INTERVAL_OUT_OF_RANGE 5,249; ANOMALOUS_SPIKE_DROP 3,765; STALE_REPORTING 3,210; ACTIVE_MPDSR_WORKFLOW 2,658; MISSING_CRITICAL_DATE 2,419; REVIEW_BEFORE_DEATH 1,032. Not cleaned. |

Tests on the committed tree:

| Suite | Result |
|---|---|
| Backend, SQLite, full | 939 passed, 0 failed, 37 skipped (35 PostgreSQL-only, 2 Redis) |
| PostgreSQL files on the disposable cluster (port 55432) | 34 passed |
| Frontend vitest | 97 passed; `tsc --noEmit` and `eslint --max-warnings=0` clean; `npm run build` succeeded |
| Playwright gate (`npm run e2e`) | **not run** |
| Redis worker, Celery Beat | **not run** (no Redis on this machine) |

## 3. What changed, and the rule each change must keep

### 3.1 Verified-run memo (`backend/app/services/calculation.py`, table `calculation_run_memos`)

A stored `CalculationRun` is returned without recalculating when one of two checks passes.

- **Same revision.** The memo was stamped at the present `global` analytics revision.
- **Same inputs** (PostgreSQL only). The `config` revision is unchanged and a database fingerprint
  of the source rows the run reads equals the one stored with the memo. For an event-based run the
  fingerprint also includes the event state.

Otherwise the existing input fingerprint (`_input_fingerprint`) decides, as before.

Rules to keep:

- The revision and every fingerprint are read **before** the rows they describe. A change committed
  in between can then only make a stored value older than the data, so a later check fails rather
  than passes. `load_sources()` calls `_source_digests` and `_event_state` first for this reason.
- The revision used is the one read for **this batch** (`batch["input_revision"]`), not the
  session-level `product_input_revision`. Using the session value returned a stale run when one
  session evaluated, changed data, and evaluated again; `test_phase3_modules.py` caught it.
- Memo stamps are written once per request, sorted by key, in one upsert (`flush_run_memos`), so two
  concurrent requests cannot deadlock on memo rows.
- A memo-hit run is loaded with `config_snapshot` and `evidence_manifest` deferred. `_selection_map`
  in `modules.py` reads the one JSON key it needs.

### 3.2 What a run reads (D-074, `_read_units` and `_child_cohort`)

A unit with district/city peers beneath it reads its own rows and rows down to the district/city
class only. Deeper rows are filtered out of `_child_cohort` candidates, out of the Python
fingerprint and out of the database fingerprint. A district and everything below it reads its whole
subtree, as before.

This is a behaviour change in one edge case: where no district holds a source key but a facility
does, a region or the country now gets cohort status `missing` instead of `incomplete`. In
`resolve_common_scope` an optional `missing` component is dropped and the formula can still compute,
whereas `incomplete` made the whole measure unavailable. The old outcome depended on whether anyone
had happened to open a district. `test_no_district_rows_cannot_fall_back_to_facilities` was updated.
The owner has been asked to confirm D-074 and has not yet answered.

### 3.3 Event-based runs are reusable within limits (D-072, `_event_state`)

`_input_fingerprint` no longer returns `None` for event formulas. It adds a digest of the retained
current Tracker events (count, oldest extraction, newest `updated_at`, newest `created_at`), every
Tracker `SyncJob` (status, window, counts, manifest), the two retention/staleness settings, and
`valid_until`. `valid_until` is the earliest of: oldest retained event plus retention, each fresh
succeeded Tracker job plus the freshness limit, and next midnight UTC. The memo stores it and a hit
requires `valid_until > now`.

The test that asserted "never reused" was replaced by one that asserts reuse while nothing changed,
a new run when an event is added, and a new run when only the clock passes the retention limit
(`test_run_reuse.py`).

### 3.4 Roll-ups (`backend/app/services/period_rollup.py`, table `rollup_states`)

`ensure_period_rollups` skips a period verified at the present revision. When the revision has
moved, PostgreSQL fingerprints each unit's rows for the period and its months, and each coverage
job. Only units whose fingerprint changed, plus units listed in the manifest of a new or changed
coverage job, are passed to `_rebuild_period(unit_ids=...)`. A pass that itself wrote rows leaves
those units out of the stored state, so the next call verifies them before the period is stamped.
On SQLite only the revision check applies.

### 3.5 Revision triggers (`backend/app/db/analytics_revision.py`, migrations 0017 and 0020)

- PostgreSQL triggers are `FOR EACH STATEMENT` with transition tables and bump only when the
  statement changed at least one row. `sync_jobs` bumps only when a `succeeded` row is involved.
- There are two counters. `global` moves for every revision table. `config` moves as well for every
  table except `raw_aggregate_values`, `raw_event_snapshots` and `sync_jobs`.
- SQLite keeps row-level triggers with the same two-counter behaviour.

The reason for 0017: with row-level triggers a bulk write updated the single `global` row once per
row inside one transaction. PostgreSQL keeps every version until commit, so the cost grew
quadratically. That, not DHIS2, was most of the two-hour MPDSR refresh, and it held the row lock
that blocked every other writer.

### 3.6 MPDSR extraction (`sync.py`, `integrations/dhis2/tracker.py`, `scripts/dhis2_refresh.py`)

- `persist_event_observations` is bulk. An event identical to its current snapshot is re-verified
  in place (`extracted_at` and `sync_job_id` updated); only new or changed events create a
  snapshot. `_same_moment` compares wall-clock values when DHIS2 sends a timestamp without an
  offset, because PostgreSQL returns it labelled with the session time zone.
- `TrackerEventsAdapter.fetch_events_result` runs peers in a thread pool
  (`DHIS2_TRACKER_PARALLEL_REQUESTS`, default 4), keeps peer order with `pool.map`, no longer sends
  `totalPages=true`, and ends a peer at a short page unless the pager supplies `pageCount`. The
  cancellation callable reads the job through the caller's SQLAlchemy session, so worker threads
  call it under a lock.
- The scheduled Tracker window is now three financial years (current and the two before).
- In eager mode the refresh script claims a job (committing `running`) before executing it, so a
  long job is visible, and records an internal failure if execution raises.

### 3.7 Self-upkeep without a worker (`local_scheduler.py`, `dashboard_precompute.py`, `main.py`)

When `SYNC_EXECUTION=eager`, the API lifespan starts a daemon thread that spawns
`scripts/dhis2_refresh.py --scheduled` as a subprocess when the last succeeded Tracker job is older
than `DHIS2_REFRESH_INTERVAL_HOURS` (default 20), no scheduled job is in progress, and the last
attempt is at least two hours old. With `DASHBOARD_PRECOMPUTE_ENABLED` the lifespan also warms
simplified boundaries in a thread and spawns `scripts.prepare_dashboards --extended`.
`prepare_default_dashboards` takes a PostgreSQL advisory lock so only one preparation runs.
`tests/conftest.py` and `scripts/run_e2e_api.py` force both settings off.

### 3.8 Smaller backend fixes

- `/me/context`: `authorised_entry_units` runs one small query per level instead of loading every
  authorised unit.
- `snapshot_map_features`: units and pinned geometries are loaded in two queries, with `geojson`
  deferred when the simplified cache will serve it. `SIMPLIFY_EPSILON_DEGREES` went from 0.01 to
  0.003 and `SIMPLIFY_VERSION` to `hpip-rdp-2`.
- Migration 0019: `analysis_snapshots` and `population_source_aliases` had `created_at` and
  `updated_at` with no default and no NOT NULL since revision 0006. Every snapshot had a NULL
  creation time, so the prepared-snapshot ordering was arbitrary and the retention purge never
  selected one. Existing rows are backfilled from `payload_json->>'generated_at'`.
- Lineage reads `provenance` for a run's source rows in one query per indicator
  (`_lineage_provenance`) instead of one lazy load per row.

### 3.9 Frontend

- `login/page.tsx`: uncontrolled inputs read at submit, button disabled until hydration, client-side
  message for empty fields.
- `globals.css` (last section, `@media (min-width: 1101px)`): roomy layout, D-070. The earlier rules
  above it are untouched and still apply at tablet and phone widths.
- `MapLibreCanvas.tsx`: unit names as HTML markers at the centroid of each unit's largest polygon.
  More than 40 units counts as crowded: the 18 largest are always shown and the rest appear after
  the viewer zooms in by 0.9. No glyph files are fetched.
- `TrendChart.tsx`, `EmptyStates.tsx`, `DashboardFrame.tsx`, `app/icon.svg`: taller chart with area
  fill per unbroken run, loading spinner with a delayed explanation, readable dates, site icon.

## 4. What I most want you to check

These are the places where a mistake would give a wrong number or a stale one. Please try to break
them rather than confirm them.

1. **Is the memo ever a hit when the inputs differ?** Enumerate everything `evaluate_formula` reads
   and confirm each input is covered by the request key, the `config` counter, the row fingerprint,
   or the event state. One gap I know of and did not close: **coverage jobs are not part of a
   run's fingerprint**, old or new. `_child_cohort(allow_partial=True)` (the `reporting_units`
   indicators, D-067) calls `_missing_month_coverage`, so a newly succeeded job could change such a
   result without changing any source row. The old fingerprint had the same gap; the new
   fingerprint path keeps parity with it rather than fixing it.
2. **Is `_event_state` a complete change detector?** It uses aggregates, not a per-row hash. My
   argument is that any insert changes the count or newest `created_at`, and any update sets
   `updated_at = now()`. Check supersede-in-one-transaction, purge, and out-of-order commits.
3. **D-074.** Confirm no formula relied on the old `incomplete` outcome, and that no other code path
   reads sub-district rows for a parent above district level. `_event_count` is deliberately
   unaffected: events are read from the whole subtree.
4. **Scoped roll-up rebuild.** A changed coverage job's reach is taken from
   `coverage_manifest["org_unit_ids"]`. If a manifest certifies units it does not list there, the
   scope is too small. A manifest without that list forces a full pass.
5. **Statement-level triggers.** `TRUNCATE` and DDL do not fire them (they did not before either).
   Confirm nothing in the application changes revision tables that way.
6. **Bulk event persistence.** Duplicate event UIDs within one extraction keep the last occurrence
   and each still counts as stored. Check that against `reconcile_event_withdrawals`, which
   withdraws rows not in `seen_row_ids` whose `extracted_at` predates the attempt.
7. **The local scheduler under more than one API process.** Two processes could both decide a
   refresh is due within the same seconds. The script's idempotency lookup is a select followed by
   an insert, not an atomic upsert. I did not test this.
8. **Quality-scan reuse.** A run on unchanged inputs is not scanned again within an hour
   (`QUALITY_SCAN_REUSE`). A prepared snapshot already tolerated six hours; check that the two
   together are acceptable for the stale-reporting rule.
9. **Parallel Tracker requests.** `Dhis2HttpClient.last_retry_count` is written from several threads.
   It is a counter only, but confirm nothing else on the client is shared mutable state.

## 5. Not done

1. **The three-year MPDSR download has never completed.** On 10 October I stopped one after 41
   minutes because DHIS2 was taking over 50 seconds a request against a 30-second timeout. The
   timeout is now 120 seconds. Today's run is the first with the final code. Until one succeeds,
   the bulk persistence and statement-level triggers are unproven at full scale, and last year's
   MPDSR comparison is unavailable. If today's job fails, the idempotency slot (six hours wide)
   means the script will not try again until 15:00 local.
2. **A first view after a data change is still calculated on demand**, 20 to 60 seconds nationally.
   Cold costs that remain: quality scan up to 30 s for MPDSR, session flushes about 15 s, roll-up
   verification about 10 s per non-month period on a first pass, MPDSR calculation about 160 s.
   Preparation covers each user's landing period and three further periods, nothing regional.
3. **Recent months are blank nationally until every district reports.** September 2026 shows no
   ANC values because 132 of 136 districts had reported. That is the governed rule (D-006, rule 7),
   not a defect, but the owner compares the platform with DHIS2, which shows partial sums.
4. The stale job rows in section 2. `scripts/recover_sync_dispatch.py` was not run.
5. The open quality flags in section 2.
6. Redis worker, Celery Beat and the Playwright gate.
7. Native financial-year aggregate requests in `dhis2_refresh.py`, contrary to D-057 (your earlier
   finding, still present).
8. Owner inputs still missing: D-069 approval, facility catchment populations, facility
   coordinates, MPDSR cause taxonomy, production formula effective dates, confirmation of D-074.

## 6. Constraints that still apply

- Never print, log, echo or commit a password, token or secret. Never commit `.env`,
  `frontend/.env.local`, database dumps, logs, `.local/`, `.next`, test results or screenshots that
  show secrets.
- DHIS2 is GET only. Do not invent UIDs, thresholds, populations, boundary dates or approvals.
- Missing is never zero. Do not cap or silently correct a value.
- Back up `hpip_live` before any migration or bulk change, and verify the dump lists.
- PostgreSQL tests run only against the disposable cluster. `HPIP_POSTGRES_TEST_URL` must never
  point at `hpip_live` or at ports 5432 or 5433.
- Do not stop the unrelated application on port 3000, or the other uvicorn processes on 8022 and
  8032. Only ports 8010 and 3100 belong to this project.
- No synthetic data in the live runtime. Never run `scripts/run_e2e_api.py` as the live API.
- Push with `git push origin master:main`, fast-forward only, and only when the owner asks.
- The DHIS2 password was disclosed in chat and must be rotated before any hosted use.

## 7. Running and testing

```
# stack (from the repository root)
powershell -ExecutionPolicy Bypass -File .\start-local.ps1
powershell -ExecutionPolicy Bypass -File .\start-local.ps1 -Rebuild     # after a frontend change

# backend, from backend/ (the parent of --basetemp must exist; keep it short for MAX_PATH)
python -m ruff check app tests scripts alembic --no-cache
python -m pytest -q --basetemp=C:/hpt/run1 -p no:cacheprovider

# PostgreSQL tests, from backend/
"C:\Program Files\PostgreSQL\18\bin\pg_ctl.exe" -D .grok-pg18-verify -o "-p 55432" start
set HPIP_POSTGRES_TEST_URL=postgresql+psycopg://hpip@127.0.0.1:55432/postgres
python -m pytest tests/test_postgres_migrations.py tests/test_postgres_fast_paths.py tests/test_postgres_concurrency.py -q --basetemp=C:/hpt/pg1 -p no:cacheprovider

# frontend, from frontend/
npx tsc --noEmit
npx eslint src --max-warnings=0
npx vitest run src
npm run build
```

Things that cost me time:

- Editing any file listed in `calculation_build_signature()` (`prepared_dashboard.py`) invalidates
  every stored run and snapshot. That is intended. The API prepares the common views again when it
  starts; expect 6 to 16 minutes of background work.
- A PostgreSQL test that fails before its cleanup leaves the database `hpip_p18_alembic_verify`
  behind, and every later PostgreSQL test then refuses to start. Drop it on port 55432 and rerun.
- The fingerprint path uses `hashtextextended`, so SQLite tests never exercise it.
  `tests/test_postgres_fast_paths.py` does.
- `scripts/dhis2_refresh.py` has no dry run and its idempotency slots are six hours wide. A second
  run in the same slot reuses the existing jobs and downloads nothing.
- DHIS2 response times vary 10 to 20 times within a day. On Saturday 10 October a Tracker request
  took 2 to 8 seconds at 10:00 and over 50 seconds at 11:40. I called this "working hours" in the
  owner handoff; that was a guess at the cause, and both days of this pass were a weekend.
- `pytest`'s shared temp folder under `%TEMP%` has been unreadable since a sandbox account wrote to
  it; always pass `--basetemp`.
- `test_concurrent_dashboards_do_not_cross_contaminate` failed once in a full run while the machine
  was also downloading and building, and passed five times alone and in two later full runs. Treat
  a single failure of it under load as load, a repeat as real.

## 8. Suggested order of work

1. Find out how today's Tracker job ended and time it. If it failed, find out why before retrying.
2. Audit section 4, items 1 to 4, with tests that try to produce a stale result.
3. Run the Playwright gate against the new layout and sign-in.
4. Then the owner's remaining complaint: first views after a change. The cheapest gains are
   probably the quality scan and preparing regional views.

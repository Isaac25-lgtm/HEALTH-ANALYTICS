# Handoff: speed, MPDSR, sign-in and layout (2026-10-10 to 2026-10-11)

Owner instruction, 2026-10-10: find out exactly why the MPDSR section does not load and why pages
take so long, fix it without over-engineering (about a hundred people at once, no new
infrastructure), test it by signing in and using it, and give the dashboards room. Later the same
day: make aesthetic upgrades as needed and report them here; put district names on the maps.

Everything below is on the local live stack (`http://localhost:3100`, live DHIS2 data). Nothing was
deployed to a hosted environment. DHIS2 was read only (GET).

## 1. What was wrong

**The pages were slow because of our own code, not the stack and not DHIS2.** One national ANC page,
profiled before any change: 123 seconds and 17,690 database queries.

| Cause | Cost per page | Fix |
|---|---|---|
| A deferred column was read row by row: one query for every source row | about 24 s (16,258 queries) | Read in one query per indicator |
| Yearly totals were rebuilt from months every time a page opened | about 23 s | Verified once per data change, and only for the units that changed |
| Every stored result was re-checked by re-reading and re-hashing all its source rows | 6 to 13 s | A stored result is recognised as still exact from one lookup, or from a database fingerprint of its own rows |
| The data-quality scan ran on every page build | 8 to 35 s | The same result, on unchanged inputs, is not scanned again within an hour |
| "Who am I" loaded all 11,000 organisation units on every page | 2.1 s | Six small queries: 0.1 s |
| Map shapes were re-read from the database for every map | 2.7 s | 0.2 s after the first map; shapes are prepared when the API starts |

**MPDSR did not load for three separate reasons.**

1. Its events are kept for 24 hours only (a deliberate privacy rule) and nothing renewed them. A day
   after each manual refresh the section went blank. There is no worker or scheduler on this
   machine, so no refresh ever ran by itself.
2. Each refresh took about two hours and blocked every other data job while it ran. Every row
   written updated one shared "data changed" counter, and PostgreSQL slows down sharply when one
   row is updated hundreds of thousands of times inside one transaction. Every event was also
   rewritten as a new row even when nothing had changed.
3. Event-based results were never allowed to be reused, so every MPDSR page recalculated from
   about 45,000 events: 163 seconds, every time it was opened.

**Sign-in failed if you typed straight away.** Text typed before the page finished loading was
discarded and the form sent empty fields ("Unprocessable Entity").

**Opening one district slowed the whole country.** Facility figures load on demand. That counted as
"data changed" everywhere, so every prepared page was thrown away and national results were
recalculated, although a national figure is summed from district rows and never from facility rows.

**Every stored dashboard snapshot had an empty creation time** (the table was created without the
default the code assumed), so "latest snapshot" was arbitrary and old snapshots were never purged.

## 2. What you get now

| Measure (national level, live data) | Before | Now |
|---|---|---|
| Sign-in to the landing dashboard | 155 s on 5 October | about 5 s |
| A prepared page | 2 to 2.6 s | 0.2 to 1.2 s |
| A page whose results exist but which is not yet prepared | about 51 s | about 7 s |
| MPDSR page | 163 s on every open, or blank | under 1 s once prepared |
| MPDSR refresh from DHIS2 | 112 minutes, blocking other jobs | 21 minutes measured on 10 October before the counter fix; see section 6 |
| Database queries for one national page | 17,690 | about 530 |
| After a restart or a day switched off | Blank MPDSR, cold pages, manual commands | The API prepares the common pages and starts the DHIS2 refresh by itself |
| Downloads (Excel, PowerPoint, Word, Markdown, PDF) | worked | all five worked: 0.8 to 5.7 s, PDF 17 s |

The first time anyone opens a view that has not been prepared since the last data change, it is
still calculated on the spot (roughly 20 to 60 s nationally). The loading indicator now says so.
The background preparation covers each user's landing period for every programme, plus the
financial year in progress and the two latest closed months.

## 3. How it works now, in plain terms

- **Results are calculated once and reused only while provably unchanged.** Each stored result
  records the data revision it was checked at. If the revision has not moved, it is returned with one
  lookup. If it has moved, PostgreSQL computes an exact fingerprint of the rows that result reads;
  if the fingerprint matches, the result is still exact. Otherwise it is recalculated. No value is
  ever taken from a result whose inputs changed.
- **National and regional figures read district rows only** (decision D-074, for your confirmation).
  They were always summed from district rows. Now they do not even look at facility rows, so
  opening a district cannot change or invalidate a national figure.
- **MPDSR results are reused within exact limits** (D-072): only while the events and
  synchronisations are unchanged and until the first moment the clock would change them (an event
  reaching the 24-hour limit, a synchronisation going stale, or midnight). The 24-hour retention
  itself is unchanged.
- **The system keeps itself current** (D-073). With no worker installed, the API starts the existing
  refresh script when the last successful MPDSR download is more than 20 hours old, at most once
  every two hours, and prepares the common pages afterwards and at every start.
- **The MPDSR download is faster and lighter.** Requests run four at a time, DHIS2 is no longer
  asked to count every event, unchanged events are marked as re-checked instead of being copied,
  and the "data changed" counter moves once per statement instead of once per row.

## 4. What changed on screen

Requested:

- Dashboards are roomy and scroll (D-070): the map takes two thirds of a row, the scorecard is full
  width with every column visible, trend and ranking panels are taller, padding is larger.
- District names on the maps: every district on a regional map; on the national map eighteen faint
  names, with the rest appearing as you zoom in.
- The signed-in name, role and geography appear at sign-in, and the dashboard opens only when ready.

My own additions, as you allowed:

- Map boundaries are drawn about three times finer (they looked angular).
- The trend chart is taller and shades the area under each unbroken run of values; gaps stay gaps.
- Best-performing and needs-attention lists sit one above the other so names are not cut off.
- A site icon (this also removes the 404 error every page logged).
- A spinner on loading, with an explanation after five seconds if the view is being calculated.
- Dates in the status line read "10 Oct 2026, 16:27"; the exact timestamp is in the tooltip.
- The top bar stays in view while scrolling; cards lift slightly on hover.
- Sign-in keeps what you type however early you type it, the button is disabled until the page is
  ready, and empty fields show "Enter your DHIS2 username and password".

Colours, the navy shell, RAG and BLUE meanings and every rule about values are unchanged.

## 5. Verification

| Check | Result |
|---|---|
| Backend full suite (SQLite), on the exact committed code | 939 passed, 0 failed, 37 skipped (35 PostgreSQL-only, 2 Redis) |
| PostgreSQL suites on a disposable cluster (port 55432, never `hpip_live`) | 34 passed, including migrations 0016 to 0020 up and down, model parity, the two-connection races and the new fingerprint tests |
| Frontend | 97 tests passed; TypeScript and ESLint clean; production build succeeded |
| Browser walk-through with a real sign-in | all 20 screens rendered, no console errors, all five downloads succeeded |
| Redis worker and Celery Beat | not tested: Redis is not installed here |

New tests: `test_seamless_operation.py`, `test_postgres_fast_paths.py`, and additions to
`test_mpdsr_minimisation.py`, `test_run_reuse.py`, `test_october_corrections.py`,
`test_admin_provisioning.py`, `login-ready.test.tsx`, `map-canvas.test.tsx`.

One rule written as a test was replaced, deliberately: "event calculations are never reused" became
"reused only until an exact clock or data change" (`test_run_reuse.py`). One expectation changed
with D-074: a region with only facility rows now reports "missing" rather than "incomplete"
(`test_october_corrections.py`); the value is unavailable in both cases.

## 6. State at handoff

On 11 October the machine had been off overnight: both servers were down and the MPDSR events had
expired at 10:22. `start-local.ps1` was run at 11:01 and nothing else was typed:

- 11:01:06 the API was up; 11:01:12 it began preparing dashboards (all 16 common views by 11:07).
- 11:01:32 it found the last MPDSR download older than 20 hours and started the refresh itself.
- 11:01 to 11:10 the twelve aggregate jobs (latest three months and FY2026/27, three programmes)
  succeeded.
- 11:10:50 the three-year MPDSR download started. **It was still running when this was written
  (11:55)**: DHIS2 is slow in working hours (item 2 below). Until it finishes the MPDSR pages show
  their figures as unavailable, which is the governed behaviour for expired events; when it
  finishes the refresh prepares the pages again. Its outcome is not recorded here.

Measured the same morning through the API, national level:

| Page | Time |
|---|---|
| Prepared page (ANC FY2026/27, immunisation FY2026/27, ANC September) | 0.3 to 1.2 s |
| Page rebuilt after a change elsewhere (ANC, intrapartum, immunisation, MPDSR, FY2025/26) | 7.2 to 11.8 s |
| "Who am I" | 0.1 s |

On 10 October the same "change elsewhere" case measured 18 to 32 s before the last two trims, and
33 to 66 s before the fingerprint work. A fresh timing with a live facility load was not repeated
on 11 October.

Two things that are data, not faults: national ANC for September 2026 shows no values because 132
of 136 districts had reported ANC1 (a national total needs every district; missing is never treated
as zero), and FY2026/27 has no yearly totals because the year is in progress. June 2026 and
FY2025/26 show values normally.

## 7. Not done, and things to know

1. **A first view after a data change is still calculated on demand** (20 to 60 s nationally). The
   background preparation covers the common views, not every period, region and district.
2. **DHIS2 is much slower in working hours.** A request that took 2 to 8 s at 10:00 took over 50 s
   at 11:40 on 10 October. The three-year MPDSR download was stopped that day rather than left
   hammering the national server; the request timeout is now 120 s (it was 30 s). The automatic
   refresh is best left to run early in the morning.
3. **The three-year MPDSR window** (needed so that last year's comparison is available) was
   introduced on 10 October; section 6 records whether it has completed.
4. **Cold MPDSR calculation is still about 160 s nationally.** It now happens in the background
   preparation, not while a person waits, unless they open an unprepared MPDSR view.
5. **Redis, the worker and Celery Beat remain untested.** The local scheduler replaces them only
   for a single-process deployment.
6. **The end-to-end Playwright gate was not run** in this pass. The browser walk-through above was
   done against the live local stack instead.
7. **A facility load interrupted by a shutdown stays "running".** One such job from 10 October is
   still marked that way. `scripts/recover_sync_dispatch.py` exists for this; it was not run.
8. **Old noisy quality flags are still open** (unchanged from the 5 October audit).
9. **Decisions for you:** confirm D-074 (section 3); D-069 (partial MPDSR reporting) stays blocked;
   facility catchment populations, facility coordinates, the MPDSR cause list and production formula
   dates are still open.
10. **The DHIS2 password was shared in chat earlier** and should be changed before any hosted use.
11. **Iron/Folic Acid shows 217.6% nationally and "On track".** That is what the approved formula
    and source data give; it looks like a definition or data-entry question, not a display fault.

## 8. Running it

```
powershell -ExecutionPolicy Bypass -File .\start-local.ps1            # API on 8010, web on 3100
powershell -ExecutionPolicy Bypass -File .\start-local.ps1 -Rebuild   # after a frontend change
```

Local `.env` settings added (not secrets): `DASHBOARD_PRECOMPUTE_ENABLED=true`,
`DHIS2_REFRESH_SCHEDULE_ENABLED=true`, `DHIS2_TIMEOUT_SECONDS=120`. Optional:
`DHIS2_REFRESH_INTERVAL_HOURS` (20), `DHIS2_TRACKER_PARALLEL_REQUESTS` (4).

Migrations applied to `hpip_live`: 0016 to 0020. Backups taken first:
`C:\Users\USER\hpip-backups\hpip_live_20261010_094850_pre_speed.dump` (510 MB) and
`hpip_live_20261010_114919_pre_0019.dump` (794 MB); both list correctly with `pg_restore --list`.

## 9. For the next engineer

| Area | Where |
|---|---|
| Verified-run memo, source fingerprints, event state, read set | `backend/app/services/calculation.py` (`_memo_run`, `_inputs_digest`, `_event_state`, `_read_units`, `_child_cohort`) |
| Roll-up verification by unit | `backend/app/services/period_rollup.py` (`ensure_period_rollups`, `RollupState`) |
| Bulk event persistence | `backend/app/services/sync.py` (`persist_event_observations`) |
| Parallel Tracker requests | `backend/app/integrations/dhis2/tracker.py` |
| Revision triggers (`global`, `config`) | `backend/app/db/analytics_revision.py`, migrations 0017 and 0020 |
| Background preparation and self-scheduling | `dashboard_precompute.py`, `local_scheduler.py`, `app/main.py` |
| Layout, labels, sign-in | `frontend/src/app/globals.css` (last section), `MapLibreCanvas.tsx`, `login/page.tsx` |

Things that will surprise you:

- Editing any file in `calculation_build_signature()` (calculation, roll-up, geometry,
  authorization, dashboard and others) invalidates every stored result by design. The API prepares
  the common views again when it starts.
- The fingerprint path is PostgreSQL only (`hashtextextended`). On SQLite the full input
  fingerprint decides, so SQLite tests cover correctness but not that path;
  `test_postgres_fast_paths.py` does.
- Fingerprints are always taken before the rows they describe are read. A change committed in
  between can only make a stored fingerprint older than the data, which forces a later check to
  fail, never to pass. Keep that order if you touch it.
- DHIS2 timestamps arrive without an offset and are stored with the session time zone;
  `_same_moment` compares wall-clock values for that reason.

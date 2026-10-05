# Codex correction handoff — 2026-10-02

## 1. Status and authority

The owner authorised a repair pass with **"fix everything"** after the September independent
audit and Claude's response. This is a code correction handoff, not an owner-acceptance certificate.
The system remains the Uganda-wide Health Performance Intelligence Platform, not a Pader-only
dashboard. Keep the approved DHIS2 hierarchy/mappings and UBOS district/city workbook. Never seed
synthetic data into the real runtime to make a screen look populated.

Starting HEAD was `a74d0e0` (preceded by `ca8cec7`). There were already 29 tracked modifications
and eight untracked files from Claude. They were preserved, including its indicator/population,
period, UI and operational-script work. The current diff is a combined working tree: do not
attribute every changed line to Codex. In particular the untracked facility service, operational
mapping/import scripts, facility/malaria tests and September 27 handoff existed before this pass.

No commit, push, hosted deployment, live database migration, live DHIS2 call, new population import,
source refresh or localhost restart was performed. `.git` is read-only for this sandbox. No `.env`
values were printed or copied, and no secrets are included here. No DHIS2 write is authorised.

The disposable PostgreSQL attempt failed at `initdb` with restricted-token/re-execution error 87.
No cluster started. Existing PostgreSQL ports 5432/5433 and the real `hpip_live` database were not
modified. Do not call PostgreSQL proof complete based on SQLite.

## 2. Changes made in this pass

### Calculation and aggregation integrity

- `app/services/period_rollup.py`: all monthly components participate in validity. An invalid
  month produces an invalid/unavailable total with all component IDs; it is not dropped to produce
  an eleven-month "year". A withdrawn month withdraws the derived total unless an actual complete
  extraction certifies non-reporting. Withdrawing all months retires the derived row. Removed the
  global maximum-extraction-time shortcut that could miss local withdrawals.
- A row in another district no longer proves that a particular unit/key/month was extracted.
  Successful sync manifests must certify programme, mapping version, unit, key and period.
  Old undocumented jobs are NOT backfilled with invented coverage.
- Native DHIS2 indicator percentages are excluded from SUM/COUNT roll-ups even when their old
  mapping is disabled. Historical disabled SUM/COUNT bindings remain supported; that is not a
  blanket approval to aggregate an arbitrary disabled or expired mapping.
- `app/services/calculation.py`: structural district/city peers cannot be replaced by facilities
  when *all* district rows are absent. Complete district totals still exclude lower-level rows.
  Approved partial-reporting calculations additionally require successful coverage for every
  absent peer; an invalid peer is not non-reporting and cannot contribute zero.
- D-067 malaria reporting policy is preserved. D-069 MPDSR reporting policy is **not approved**:
  `MPDSR_REPORTING_UNITS_APPROVED` defaults false, so partial MPDSR aggregation is blocked. The
  premature version/history is preserved rather than rewritten or deleted.
- Low-level reuse fingerprints now include event mappings, source identity/invalidity/absence/
  freshness and hierarchy validity, plus a calculator build digest. Historical hierarchy and
  event-subtree caches are keyed by both geography and period, not geography alone.
- `geography.py`, `authorization.py`, `modules.py`, `mpdsr_events.py`: closed facilities with a
  recorded closing date remain visible in their earlier valid periods. Inactive undated units do
  not become universally available. Server-side geography/programme/action checks remain mandatory.
- `dashboard.py`: sub-county screens now receive the facility comparisons/scorecard, like district
  screens. Existing unavailable population-derived facility percentages are not manufactured.

### Prepared dashboard reads and sign-in

- New `app/services/prepared_dashboard.py`: prepared products are existing **private** immutable
  analysis snapshots. An exact matching request reads the snapshot instead of rebuilding roughly
  175 runs. Scope, creator, programme and action are rechecked. No shared-user result cache was
  introduced.
- New `AnalyticsRevision` model and `app/db/analytics_revision.py`: source/reference/configuration
  table writes invalidate prepared products transactionally, including bulk SQL updates. Queued
  and running sync progress does not invalidate products; successful coverage changes do.
- New frozen migration `0015_sync_coverage_manifest`: adds `sync_jobs.coverage_manifest`, the
  analytical revision table/triggers, a prepared-snapshot lookup index and a partial unique guard
  for active facility jobs. Historical revisions 0001–0014 were not rewritten. The test `create_all`
  hook installs equivalent triggers only for explicit test databases; production uses Alembic.
- An input revision is captured before material source reads. If it changed during preparation,
  the result does not receive a reusable preparation signature. The signed revision is the one
  actually observed, not a second newly fetched revision that could incorrectly label old inputs.
- Prepared metadata includes calculator/configuration identity and a bounded expiry (at most six
  hours). MPDSR products expire no later than relevant retained-event and coverage freshness
  deadlines or the UTC date boundary. Reopening an explicitly saved historical snapshot remains
  a read of that historical evidence, not a claim that it is today's live extract.
- `GET /analytics/dashboard/prepared` is a read-only ready lookup. Invalid periods are 422, current
  permissions are checked and historical valid units are supported. The existing CSRF POST can
  reuse a valid prepared product; its cold path still calculates and persists a new snapshot.
- Routine MNCH/EPI batches no longer SELECT/deserialise MPDSR events. This removes the major
  unrelated event-loading cost identified in the audit. Event formulas do not use the old unsafe
  hour-bucket low-level reuse.
- New `dashboard_precompute.py`, `scripts/prepare_dashboards.py`, and maintenance task: prepare
  active users' authorised latest-closed-FY default views from governed data, skipping inactive,
  unprivileged or unassigned users. This is not an API startup bootstrap or a synthetic seeder.
- Successful durable sync can dispatch preparation when `DASHBOARD_PRECOMPUTE_ENABLED=true`.
  If broker publication fails after committing an extraction, the task records the failure and
  a retry can dispatch preparation for that already-succeeded extraction; it does not relabel
  the successful extraction as failed.
- `frontend/src/app/login/page.tsx`: authenticate once, clear the password, show verified display
  name/username, role and landing geography, prepare/read the dashboard, load the authorised child
  list, then navigate directly to the saved snapshot. Preparation failure stays at sign-in with a
  retry that does not need another password. A completed but all-unavailable landing result is
  **not** treated as a usable dashboard.
- Backend sign-in updates the stored display name from the authenticated DHIS2 profile. It does
  not import remote roles or expand local grants.
- New `dashboard-ready.ts`: a 30-second, memory-only navigation handoff. It contains no token and
  is cleared on logout/new authentication. `DashboardView.tsx` validates a primed snapshot against
  URL geography/period/module/comparison/indicator, uses prepared reads, and avoids the extra
  request-key redirect before querying. Filters/period selectors resynchronise with new results.

### Durable, authorised facility loading

- `facility_data.py` selects a unique enabled in-force mapping version instead of hard-coding a
  September version. Load/status scope is the requested facility/sub-county/district subtree, not
  a wider district that a facility user did not request.
- VIEW, programme and geography are checked before queuing. The worker rechecks the initiating
  user's active state and current permissions; revoked authority fails the job before upstream
  retrieval. System-scheduled jobs remain an explicit internal path.
- Work is dispatched to the existing durable sync worker after commit, not performed as a long
  ASGI background HTTP task. Explicit test/development eager mode remains available; production
  does not silently switch to it.
- Stable active-job identity, PostgreSQL transaction advisory locking and the partial unique index
  protect concurrent duplicate queueing. SQLite uses the constraint/savepoint path as a test guard.
- A job's finish date alone is not "ready". It must have complete matching coverage, no truncation/
  cancellation/rejections, the current expected facility cohort and mapping IDs. If its reported
  raw rows were purged, its old successful manifest does not pretend those rows are still present.
- Recent recheck uses exactly the two most recent closed months. Prefetch uses savepoints so a
  programme-specific failure cannot corrupt the sign-in transaction. Enqueue failure is recorded.
- `FacilityDataBanner.tsx` avoids overlapping polls and stops with an explicit retryable message
  instead of silently leaving a ten-minute timed-out load labelled as permanently loading.

### MPDSR coverage, privacy, quality and scheduling

- Tracker selects all configured programme forms, bounds retrieval through today and records the
  actual programme UIDs/mapping IDs in its manifest. Multi-form zero certification requires all of
  them, not the old single-form check. Truncated/partial/failed/cancelled work cannot prove zero.
- Persistence counts unusable death dates without retaining their free text. Such an extraction
  cannot certify an empty cohort as genuine zero. Positive matched counts retain their coverage
  status; they are not magically converted into proof of full upstream date completeness.
- Approved program UID selection respects mapping validity for the cohort. Analytical reads apply
  the short event-retention cutoff. MPDSR-only freshness includes event-backed data rather than
  incorrectly claiming "no source rows" solely because no aggregate row exists.
- `tracker.py` can discard unapproved data elements before creating EventObservation objects, and
  sync passes the approved mapping whitelist. Upstream HTTP JSON may still briefly contain other
  fields in memory. The persistence whitelist remains authoritative. Do not repeat the unsupported
  earlier claim "identifying fields were never extracted"; no raw line list is sent to external AI.
- Sensitive saved MPDSR extras also recheck `view_mpdsr_events` on retrieval. Losing that action
  cannot be bypassed by retaining a snapshot UUID from an earlier session.
- A non-administrator's active grant no longer keeps a disabled programme accessible. Scheduled
  refresh also excludes disabled programmes. These last scope guards have a separate focused test;
  they were added after the full rerun started and still need inclusion in the operator's full gate.
- Missing-cause checks require an approved taxonomy and enabled cause mappings for the form. If
  cause capture is deliberately withheld, it does not generate new "missing cause" flags.
- Stale reporting by age is confined to the latest/current operational reporting windows, rather
  than flagging the entire extracted history. Open/acknowledged flags are grouped for the bell;
  detailed quality records remain available through authorised history APIs.
- `celery_app.py`: opt-in six-hour refresh and existing hourly purge schedules on the maintenance
  queue. `dhis2_refresh.py` adds current/latest-closed-FY MPDSR Tracker windows through today;
  aggregate history is not repeatedly swept. Deliberately unresolved source keys do not disable
  every otherwise usable approved mapping set.
- Scheduling is **code only**, disabled by default. No Redis worker/Beat or Render cron was started.
  Existing obsolete cause/stale flags were not deleted or bulk-resolved in the live database.

### Maps, exports and operational permission checks

- `geometry.py`: saved map features use their pinned geometry IDs, not today's replacement
  geometry. Missing pinned geometry is not silently substituted. Legacy snapshots without an ID
  use an explicit dated compatibility lookup. Closed valid historical units can reopen.
- PDF trends split into contiguous segments at missing months. They no longer draw a line across
  a missing period while the caption claims gaps. Source names/notes passed into ReportLab
  Paragraphs are escaped; approved formatter markup stays formatter-owned.
- Excel text cells inferred as formulas are forced to literal text. Source text beginning with
  `=` cannot execute as a spreadsheet formula; numerical measure cells remain numerical.
- Export unit grids match the visible comparison/facility table rather than silently using the
  different district-map cohort. A selected facility's map receives its own snapshot value.
- PDF and editable PowerPoint maps preserve interior polygon rings and support Point/MultiPoint
  features. No missing geometry or coordinates were invented. Ranking bars share a consistent
  scale; a genuine zero is not drawn as a minimum-height positive bar.
- `apply_direct_indicator.py`, `apply_mpdsr_event_mappings.py`, `import_live_subunits.py` now require
  the appropriate action/programme/root-geography authority and explicit approval reference.

## 3. Test integrity and evidence

Tests are isolated structural/number fixtures, never a replacement for the real DHIS2 runtime.
No regression was removed or marked skipped to make a failure disappear.

Legitimate fixture/assertion changes:

1. Non-reporting roll-up/malaria tests now supply explicit complete unit/key/month extraction
   manifests. Their numerical assertions are unchanged.
2. Facility readiness fixtures now include mappings, manifests and requested facility cohort.
   Finish timestamps alone deliberately do not satisfy the stronger contract.
3. Event low-level reuse tests now assert non-reuse because the old hourly clock policy was unsafe;
   separate prepared-product tests prove safe reuse, invalidation and read-only behaviour.
4. Visible export-grid assertions use strict equality with the visible scorecard cohort, not a
   permissive subset of the different map cohort.
5. Two ingestion fixtures now name the authorised job programme/geography. Their invalid-value and
   persistence assertions are unchanged; production no longer accepts an unscoped programme job.
6. The isolated demonstration-catalogue test supplies explicitly labelled district test rows,
   rather than expecting a facility-only fixture to stand in for absent districts. No demo seeder
   or real population source was changed or run.
7. Retention test changes a source before making its second request and asserts different snapshot
   IDs. An unchanged request now correctly reuses a product. Its retained-versus-unreferenced
   deletion assertions are preserved.
8. Migration tests expect the new head and continue checking frozen migration history. A new
   PostgreSQL-only test exercises migration-created revision triggers and the active facility
   index, including the fact that queued progress must not invalidate ready products.

New independent regressions are in `backend/tests/test_october_corrections.py` (21 tests), plus
four ready-sign-in tests in `frontend/src/test/login-ready.test.tsx`. They cover invalid/withdrawn
months, geography fallback, zero certification, retention/readiness, prepared read-only reuse,
bulk invalidation, revision changes during preparation, exact geometry, export injection/gaps/
holes/points, historical facilities and sensitive snapshot permissions.

Verification ledger (update only with observed results):

| Check | Result |
|---|---|
| Backend Ruff (`app tests scripts`, no cache) | Passed after final Python code changes |
| First full backend run | 894 passed, 2 failed, 32 skipped, 1443.37s; the two fixture premises above were corrected. Not a final-tree pass. |
| Focused combined run before PDF API correction | 145 passed, 3 failed; all three exposed the new renderer calling `Path.close()` instead of `closePath()`. Fixed, not ignored. |
| Corrected focused backend run | 75 passed, 183.93s: October regressions, publishing visuals, SQLite migrations, facility jobs, demonstration fixtures and retention |
| Final permission guards | 2 passed, 2.56s: disabled programme grants and sensitive snapshot access. The new snapshot test initially lacked required fixture metadata/programme scope; these were supplied without weakening its permission assertion. Ruff remained clean. |
| Final full backend run | Reached at least 54% without a reported failure. Its execution handle became unavailable at the subsequent status turn; no final total is available and no final pass is claimed. Rerun on the exact final tree. |
| Frontend TypeScript | Passed after final facility-banner type correction |
| ESLint | Passed after final frontend changes |
| Application Vitest | 95 passed (92 existing + 3 initial sign-in tests), then all 4 sign-in tests passed after adding the empty-result guard |
| Full npm test including process-gate tests | One clean-run process-gate test failed while a concurrent lint process created foreign Node processes detected by the restricted-account baseline-delta check. No assertion was weakened. Run this gate serially under Claude's account; no final full npm-test pass is claimed. |
| Production build | Not verified. Scratch build first hit a basename safety guard, then a correctly named copy failed resolving Next client modules through a C:-to-F: node_modules junction. No guard was weakened. |
| Disposable PostgreSQL | Blocked by initdb restricted-token error 87; no PostgreSQL test pass claimed |
| Real Redis/Celery, browser gate, Docker, real-data timings/downloads | Not executed in this pass |

No build/test artifact was written into checkout `.next`, no owner file was deleted, and no
quarantined folder was removed. Python/test/build scratch work went into distinct Windows temp
directories; temporary build dependency junctions refer to checkout dependencies, so never
recursively delete through those links. Existing build quarantine remains the owner's housekeeping.

## 4. What is NOT finished

This pass is not an exhaustive closure of every September finding. In particular:

- **Cold performance:** no target under 1s/2s is proven. A cache miss still performs the heavy
  calculation POST. Warm defaults can be prepared after extraction; uncommon geography/period/
  comparison/indicator combinations are not comprehensively precomputed. Global revision
  invalidation is conservative and can evict unrelated programmes. Source-row triggers may
  serialise concurrent writers; profile national ingestion before tuning their granularity.
- **Roll-up scope:** the dangerous global timestamp shortcut is gone, but cold materialisation
  still scans broad stored monthly groups. Incremental programme/geography/component-scoped
  materialisation and durable coalescing remain work, not a claim of completion.
- **Refresh completeness:** old jobs lack explicit coverage. They cannot certify absence without
  a new actual scoped extraction. Do not backfill manifests from assumptions. Reconcile every
  long-period aggregate request path with D-057's monthly-source contract, and prove mapping/unit
  validity for all months in a multi-month job, including a cohort change within a year.
- **Tracker ingestion:** national retrieval still accumulates substantial observations in memory.
  Bounded streaming/staging and complete-refresh withdrawal reconciliation need implementation/
  proof before this is described as scalable and restart-safe across large extracts. Existing
  partial/old events cannot be silently interpreted as a complete reporting cohort.
- **MPDSR operation:** death-date free-text/incompleteness is an upstream/governance limitation.
  The new zero guard prevents false assurance, not recovery of those dates. Old events may already
  be expired. Cause taxonomy/disclosure remains unapproved; no cause data was invented.
- **Queue/scheduler:** prepared code is not a running schedule. Prove restart recovery, revocation,
  duplicate delivery and two-connection PostgreSQL facility queueing. Run one scheduler; avoid
  simultaneously enabling Beat and an equivalent cron. Test fresh Tracker extraction and purge
  together; do not simply purge the only retained case cache and call MPDSR operational.
- **Old flags:** new false-positive generation is curtailed, but live obsolete flags remain until
  an audited cleanup. Existing immutable snapshots intentionally retain their historical content.
- **Owner inputs:** D-069, facility/sub-county populations, missing boundary/coordinate approvals,
  official branding/templates, remaining four source definitions, effective formula dates for
  hosted production, AI/provider approval and monitoring/restore sign-off remain real gaps.
- **Acceptance:** final build/browser/PostgreSQL/Redis gates and supervised live-data comparison
  have not passed here. No percentage-readiness claim replaces those gates.

## 5. Claude/operator handoff — execute in order

1. Read AGENTS, canonical/context decisions and this handoff. Preserve the combined working tree.
   Inspect `git status`/diff/untracked files; do not discard Claude's existing changes or falsely
   claim this batch was already committed. Do not print `.env` or use credentials on command lines.
2. Review the remaining code items in section 4. Fix/prove them systematically; do not treat this
   handoff as permission to invent thresholds, missing UIDs/populations, a taxonomy or D-069 approval.
3. On a **disposable** PostgreSQL instance, set `HPIP_POSTGRES_TEST_URL` privately and run the full
   backend suite. This variable must NOT identify `hpip_live`, ports 5432/5433 or an unrelated store.
   Include empty→head, 0014→0015, downgrade/re-upgrade, model/migration parity, transactional
   revision rollback/concurrency, the new active-job guard and two simultaneous facility requests.
4. Run Ruff, TypeScript, ESLint, all Vitest/script-gate tests, `npm run build` in the real checkout,
   Playwright and the real Redis/worker tests. Use your normal permitted account so build output
   does not become inaccessible. Validate export PDF/PPT point/polygon holes and gap charts visually.
   Failures are failures; do not weaken assertions or clear skips without actually running them.
5. Inspect live listeners before restart. The September 27 handoff specified web 3100/API 8010,
   whereas earlier notes specified 3000. Honour the actual configured same-origin web URL and do
   not kill another project. Do not replace the real API with `run_e2e_api.py`.
6. Only after disposable PostgreSQL proof, take and verify an approved backup of the real local
   control store; apply `python -m alembic upgrade head` with the operator's private configuration.
   Do not bootstrap another country, duplicate hierarchy/population, or change approved versions.
7. Configure the existing Redis worker/maintenance queues and a single opt-in scheduler, according
   to approved topology. Preserve D-057's aggregate retention and short MPDSR retention. Confirm
   actual job execution, failures/retries, purge, and last-success freshness in the database/logs.
8. Run a supervised **GET-only** DHIS2 refresh using approved mappings, Uganda-wide scope and
   exact non-overlapping district/city peers. Produce real coverage manifests, not synthetic
   ones. Compare source extracts, district totals and national totals; demonstrate missing and
   invalid components are unavailable rather than zero. Keep identifiers out of logs/reports.
9. From `backend/`, run `python -m scripts.prepare_dashboards` after the successful refresh (or
   programme-specific warming), then test `/analytics/dashboard/prepared` and actual sign-in.
   Prove a repeat ready view creates no runs/jobs, a source/mapping/population change invalidates
   it, an expired MPDSR view does not certify zero, and revoked permissions block saved snapshots.
10. Measure real first/warm national, regional, district and sub-county views separately. Report
    authentication, ready lookup, preparation, payload transfer and rendering times; do not
    claim a sub-second live SLA based on fixture tests. Check account identity, data timestamps,
    configured populations, map level and every download against the exact on-screen snapshot.
11. With owner direction and successful gates, stage only reviewed code/tests/docs (not `.env`,
    workbook copies, dumps, logs or generated artifacts), commit and push to the verified intended
    remote/branch. This instruction does not authorise hosted go-live. Restart localhost on that
    committed code and report exact URLs, commit, job/freshness evidence, test totals/skips, timing
    evidence and remaining owner decisions. Do not say "everything perfect" or "live" merely
    because servers listen or unit tests pass.

The owner has already supplied the district/city population workbook and approved national
analysis. The remaining work is verification, specific unresolved contracts and operator activation,
not another request for the same workbook or a fabricated demo.

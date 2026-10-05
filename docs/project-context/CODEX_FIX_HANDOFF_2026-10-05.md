# Codex follow-up fixes and operator handoff — 2026-10-05

## Scope and current status

The owner instructed "fix them" after the independent review of Claude's verification report.
This pass repairs four confirmed code gaps and their closely related queue/scope safeguards.
It preserves the existing combined working tree and the earlier October corrections. It does
not certify that every remaining production or performance task is finished.

HEAD remains `a74d0e0`. Nothing was committed, pushed, deployed, restarted or migrated. No DHIS2
request was made and no upstream write was made. No workbook was reimported, no population or
clinical rule was invented, and no synthetic observation was put into the real runtime. Secrets
from `.env` were neither printed nor copied. The repository's earlier modifications belong to
the combined Claude/Codex work; do not attribute the entire diff to this follow-up.

Read this alongside `CODEX_CORRECTIONS_2026-10-02.md`, the canonical handoff, AGENTS and the owner
decisions. This is an engineering handoff, not an owner-acceptance certificate.

## 1. Complete refreshes now reconcile withdrawals

Before this fix, a successful request returning no rows did not make previously returned rows
non-current. The earlier roll-up correction could handle a withdrawn month, but ingestion did
not necessarily withdraw it. Tracker had the same stale-current-record problem.

New `backend/app/services/sync_reconciliation.py`, called by `sync.py`:

- Reconciles only succeeded, complete, uncancelled extractions with programme/mapping identity,
  no rejected observations and no page cap. Failed/partial/truncated/cancelled work does not
  certify absence and cannot sweep previous evidence.
- Aggregate scope is the actual requested unit/period/source-key/item/COC combination, programme,
  mapping version and DHIS2 source, further constrained to the job's target subtree. A total-only
  request never certifies absence of a category-specific row. Counts
  requested from peers cannot acquire coverage merely because a direct percentage requested a
  parent in the same job.
- Tracker scope is the actual requested forms and root subtrees, programme, mapping version,
  connector and recorded occurredAt retrieval window. Null/out-of-window occurredAt records,
  unrequested forms and other geography are not certified absent by that request.
- Tracker requests explicitly use `DESCENDANTS`, matching the approved non-overlapping peer
  policy and the scope being certified. The manifest records this mode.
- Date-only Tracker window arguments now expand to explicit day-start/day-end timestamps;
  timestamp arguments retain their supplied time/offset. This makes the already-approved
  full-day request window unambiguous, rather than relying on a server's date-only interpretation.
  DHIS2 2.41 documents these filters as ISO-8601 DateTime parameters; this is a defensive precision
  fix, not proof that the live instance previously omitted end-day events.
  [DHIS2 2.41 Tracker API](https://docs.dhis2.org/en/develop/using-the-api/dhis-core-version-241/tracker.html).
- Persistence returns the IDs seen in this attempt to reconciliation. A retry's old partial
  rows are not protected merely because they have the same job ID; newly returned rows are.
- Rows extracted after this attempt started cannot be withdrawn by its omission sweep. This
  protects newer evidence during overlapping refreshes; it is not a claim that all out-of-order
  returned-value persistence across overlapping jobs has been redesigned.
  A recorded attempt start is required; database creation timestamps truncated to seconds are
  not substituted for it. Legacy jobs without a recorded start cannot sweep source rows.
- Both reconciliation scans use keyset batches of at most 500 rows; cursors finish before
  updates. This bounds the reconciliation scan, not the entire upstream extraction pipeline.
- Withdrawn rows become non-current, not deleted. Aggregate provenance records the withdrawal
  job/time/reason; Tracker job manifests and safe operational events record counts. No event UID
  lists or identifying line lists are added to those manifests/logs.
- Existing revision triggers invalidate prepared products transactionally when current facts
  change. Saved historical snapshots and evidence are not rewritten.
- New exact `requests` dimensions are understood by `period_rollup.py`. Old jobs without real
  coverage are not backfilled with assumed requests.

Regression: twelve monthly values of 10 produce 120; a complete fresh June extraction returning
no row withdraws the prior June row and the old year. A new derived 110 records the explicitly
certified non-reporting month and coverage job under the existing approved non-reporting policy.
No reported-zero source row is invented. An incomplete extraction leaves the old row intact.
Other mappings/versions/periods/units/COCs and returned facts remain untouched.

Important limitation: withdrawal sweep is deliberately mapping-version-specific. This is not an
automatic retirement policy for every old version, nor proof of every historical mapping change.

## 2. Quality respects short MPDSR retention

Previously, analytical MPDSR reads excluded expired events but the quality scanner could still
read those events and generate fresh flags.

- `mpdsr_events.py` now exposes one shared `retained_mpdsr_events` reader for authorised dated
  geography, MPDSR programme/form scope, current Tracker rows and the configured retention cutoff.
- The analytical wrapper adds the death-cohort filter. Quality uses the retained reader before
  its existing cohort checks, preserving useful missing-death-date checks rather than hiding
  undated retained evidence.
- Other programmes/connectors and expired rows cannot generate new flags through this scan.
- The existing legacy null-programme compatibility path is preserved, with approved form checks;
  this does not widen the public API or approve new forms.

No old live flags were deleted/resolved and no expired live events were purged in this pass.
An audited cleanup and a new complete governed refresh are still operational work.

## 3. Sign-in queue recovery and publication races

Two problems were confirmed: a later programme's prefetch failure could discard earlier dispatch
IDs, and a crash between committing a job and publishing it could strand that durable job.

- `facility_data.py` isolates each programme in its own savepoint and exception handler. Earlier
  successful IDs survive a later failure; the failing programme's partial job rolls back.
- Broker-failure handlers in the facility service and sync API use conditional SQL updates of
  still-queued, uncancelled work. A worker that already claimed the task cannot be relabelled
  failed just because the publisher lost an acknowledgement. Safe codes/messages replace broker
  exception details; prefetch/publication warnings do not log exception traces.
- New `sync_recovery.py` recovers existing SyncJob records, without another job store, raw-data
  cache or migration. It selects bounded batches of old queued/unstarted jobs and explicit
  unstarted publication failures only. Cancellation, running jobs and extraction failures are
  not revived. An old failed facility key with an active replacement is not revived alongside it.
- A conditional update commits the retry clock before broker publication. A crash on either
  side remains retryable after the delay. Delivery is **at least once**, not exactly once; the
  existing worker claim and PostgreSQL execution lock protect extraction from duplicate delivery.
- Failed publication stays recoverable with a safe error. Facility status continues polling the
  same job instead of claiming it is loaded or immediately creating a replacement.
- The existing maintenance queue receives `app.workers.tasks.recover_sync_dispatch` every 60s
  when DHIS2 and sync are enabled and `SYNC_EXECUTION=queue`. A single operator-started scheduler
  and actual maintenance worker are required. Code alone does not start them.
- New operator CLI: from `backend/`, `python -m scripts.recover_sync_dispatch --limit 100`.
  It reports safe counters and exits non-zero on publication failures. It does not itself extract
  DHIS2, but it publishes jobs that an enabled worker can execute. Use only with approved private
  runtime configuration and after reviewing pending work; it was not run against the live store.
- A fresh-process CLI check exposed an import-order cycle that the already-initialised pytest
  application masked. Recovery now imports observability after connector initialisation. A
  subprocess regression verifies disabled startup with no database schema and empty credentials.
- Recovery is inert when extraction is disabled or execution is eager/test mode. Batch size is
  bounded to 1–1000 and the default minimum retry age is 60 seconds.

## 4. Closed facilities remain accessible in dated history

The earlier geography reader supported history, but some facility routes still passed no period.

- Facility queue access, dashboard facility-status access and initiating-user worker rechecks
  now pass the requested period.
- `_facility_uids` selects descendants using the extraction date's month instead of current-only
  activity. Dated closed facilities can participate in their earlier valid period.
- Current role/action/programme/grant checks are NOT weakened. An inactive/revoked user still
  cannot execute a historical job. Units outside their historical validity remain unavailable.

The regression exercises the real dashboard POST and status GET for a closed facility in June,
denies the later invalid period, and proves worker revocation still prevents upstream execution.
This does not solve every within-year cohort or mapping change in multi-month extraction.

## 5. Changed surfaces in this follow-up

- New services: `sync_reconciliation.py`, `sync_recovery.py`.
- Modified services: `sync.py`, `period_rollup.py`, `mpdsr_events.py`, `quality.py`, `facility_data.py`.
- Modified routes: `api/routes/dashboard.py`, `api/routes/sync.py`.
- Modified worker registration/configuration: `workers/tasks.py`, `workers/celery_app.py`.
- Modified Tracker adapter: `integrations/dhis2/tracker.py` (explicit date-window timestamps).
- New CLI: `scripts/recover_sync_dispatch.py`.
- New regressions: `tests/test_october_followup.py`.
- Added two PostgreSQL races in `tests/test_postgres_concurrency.py`: two users queue the same
  facility scope through the actual service, and two recovery sessions compete for publication.
- Updated this handoff, OPEN_ITEMS, DEFECT_MATRIX, CHANGELOG_CONTEXT, LOCAL_DEVELOPMENT and
  ENV_REFERENCE. No migration or frontend source was added/changed by this follow-up.

## 6. Verification ledger

All new source observations are isolated test fixtures, not runtime substitutes for DHIS2.
Existing product assertions were not removed or weakened. The first targeted run exposed three
fixture premises: the withdrawal fixture used the synthetic source label rather than DHIS2;
an initiating-user change had not been flushed before the worker refreshed its job. The source
label affected two withdrawal tests; the unflushed initiator affected one worker test. Those
premises were corrected, not the assertions.

Two pre-existing date-bound assertions in `test_phase12_corrections.py` and
`test_amendment_sync_freshness.py` now expect exact full-day timestamps instead of date-only
parameters. They retain exact equality, the approved date interval and the through-today bound;
neither period bounding nor completeness assertions were removed or made permissive. No new
clinical/death-date or timezone decision was invented.

The attempt-start guard additionally exposed SQLite's second-resolution database creation
timestamp. Reconciliation now requires the worker's actual start; fixture running/succeeded jobs
record that start too. The precision/overlap protection was not removed to obtain a pass.

| Check | Evidence |
|---|---|
| Focused combined backend regression run | 138 passed in 109.43s before the final batching/extra-regression changes; not a final-tree full-suite certificate |
| Backend Ruff, `app tests scripts --no-cache` | Passed after the final Python changes |
| Follow-up regressions before the final Tracker timestamp correction | 28 passed in 31.67s after the fresh-process CLI correction, including category/overlap/time-precision and disabled CLI startup guards |
| Fresh-process recovery CLI | Initially failed with circular import; corrected and rerun successfully with isolated memory DB/extraction disabled (all dispatch counters zero) |
| Full backend, isolated SQLite/test runtime | 928 passed, 35 skipped (33 PostgreSQL, 2 Redis), 0 failed in 907.50s; read the timing qualification below |
| Final affected-services/connector regression run | 182 passed, 0 failed, 0 skipped in 201.94s on the final frozen Python code, including all 29 follow-up cases and the strengthened Tracker request assertions |
| Full-run timing qualification | The full run collected before the last CLI import and Tracker timestamp corrections. An additional combined regression run on the final frozen code covers all affected services/connector contracts; do not conceal this qualification when reporting an exact-final-tree full gate. |
| Interrupted earlier full/focused runs | Execution handles became unavailable after the owner's interruption; no final pass is claimed. Restarted the full suite on the final frozen code with a JUnit report in private temporary storage. |
| New PostgreSQL race tests | Added, not executed here. After the owner said access was restored, a fresh PostgreSQL 18 initdb attempt in a unique temporary location still failed with restricted-token error 87/re-execution error 3. No cluster started or shared database was modified. Execute under Claude/operator's normal permitted Windows account. |
| Real Redis/broker/restart recovery | Not executed here |
| Frontend | No source changes this follow-up; earlier independent 115-test run remains earlier evidence, not a new build/browser gate |
| Claude's earlier PostgreSQL/build results | Reported 53 PostgreSQL tests and production build passed on the prior tree; not independent verification of the new recovery/race code |
| Live migration/refresh/purge/flag cleanup/timing | Not executed |

## 7. Exact remaining operational work for Claude/operator

1. Review the combined diff and untracked files, including this follow-up. Do not discard existing
   work or copy secrets into Git. Run the backend suite on the final tree using a private temp
   directory; use a disposable PostgreSQL instance for all PostgreSQL tests, never `hpip_live`.
   Exercise both new two-connection races, migration 0015 rollback/re-upgrade and revision triggers.
2. Prove recovery with real Redis/Celery: commit without publishing, broker unavailable, lost
   acknowledgement, duplicate delivery, API restart, worker restart and revoked initiating user.
   Include simultaneous recovery sweeps and a replacement facility job. Demonstrate no upstream
   request outside current authorised scope and no duplicate extraction under the execution lock.
3. Inspect the actual live revision privately. The last independent read-only audit observed
   **0014**; these combined corrections require **0015**. After disposable proof and approved
   verified backup, apply the migration. Never drop/reseed the live database or duplicate UBOS data.
4. Start/restart the actual persistent API/frontend with the operator's private configuration,
   existing hierarchy/populations and correct origin/ports. Never launch the synthetic E2E server
   as the owner's site. Start the existing worker queues and exactly one approved scheduler, or
   an approved equivalent recovery invocation; do not assume schedule registration means operation.
5. Perform a supervised, bounded, GET-only live DHIS2 refresh with approved Uganda-wide mappings.
   Check complete extraction manifests and withdrawal counts against upstream data. Test partial
   failure without stale-evidence loss. Refresh MPDSR before treating it as current; preserve the
   approved aggregate history and short MPDSR retention. Purge/refresh must work together.
6. Audit old false flags with reasoned lifecycle transitions; do not mass-delete historical flags
   or immutable snapshots. Causes remain withheld without the approved taxonomy/disclosure rule.
7. Prepare authorised default dashboards after refresh. Measure real cold and warm national,
   regional, district, sub-county and facility views, including authentication/preparation/render
   timing. Prove ready sign-in, exact-repeat pure reads, retention expiry, changed-source invalidation,
   historical closed-facility access and safe downloads from the displayed snapshot.
8. Run the normal account's frontend build/Playwright and all Redis tests. Keep gate tests serial;
   competing foreign build/test processes can make restricted-account process checks fail. Do not
   write another account's build output into the shared checkout or weaken checks to obtain a pass.
9. Only after review and owner direction, commit/push reviewed code/tests/docs to the verified
   remote/branch. Report the actual commit, local URLs, coverage/freshness evidence, test totals,
   skips and measured timings. This document is not permission for an unapproved hosted go-live.

## 8. What is still not completed by these fixes

The live store, expired event cache and old flags were not changed. Workers/scheduler and fresh
source extraction were not activated. National live speed is not measured. Cold uncommon views
still calculate synchronously, broad roll-up work is not fully incremental, upstream Tracker
extraction still accumulates observations in memory, and multi-month mapping/cohort validity plus
all aggregate request paths still require the earlier October engineering review. These are real
remaining tasks, not owner-input excuses or proof that the supplied district populations are missing.

D-069, facility/sub-county population contracts, cause taxonomy/disclosure, hosted formula dates,
unresolved definitions/assets and production operations remain governed inputs. Existing national
UBOS data and approvals must be preserved, not requested or fabricated again.

No new credentials were requested. Use the operator's existing private, authorised configuration;
do not ask the owner again for the already supplied district/city workbook or approved national
UID mappings. Outstanding approvals are specific contracts, not permission to substitute a demo.

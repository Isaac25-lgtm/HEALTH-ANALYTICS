# Independent audit — 11 October 2026

## Verdict

**The performance improvements are real, but the new fast paths are not yet safe to accept as
provably correct.** I reproduced stale calculated numbers and a stale yearly total on actual
PostgreSQL on the disposable cluster at port 55432. This is not a claim that Uganda's presently
displayed figures have all been corrupted: the counterexamples establish failures of the current
code under specific changes/concurrency, without altering the live data.

Most serious: scoped yearly verification can miss a concurrent month replacement, and a calculation
can then read the stale year at a newer analytics revision. Separately, run memos omit extraction
coverage and can pair an old fingerprint with newer calculated inputs. The MPDSR aggregate
event-state detector can miss an out-of-order committed event change.

The live Tracker job succeeded, and event-derived counts are available again. Physical event
retention, interrupted facility work and browser acceptance are not finished.

## Authority, baseline and methods

Read in the requested order: AGENTS, CODEX_HANDOFF_2026-10-11, CLAUDE_HANDOFF_2026-10-11,
then decisions D-070 through D-075. No audit-action conflict with AGENTS required a prohibited
operation. D-070 explicitly supersedes the earlier desktop one-screen density clause; it does
not revoke the blue/navy visual contract or calculation rules.

- HEAD and local `master`: `e932d47`, preceded by `d07ac8f`.
- At entry, `CODEX_HANDOFF_2026-10-11.md` was untracked. Thus the handoff's clean-tree statement
  was not true at audit entry, though no tracked implementation diff was present.
- No production code, calculation-build-signature file or existing assertion was edited.
  No build-signature invalidation was caused by this audit. Future approved changes to those
  files invalidate active run reuse/prepared lookups after process restart; saved historical
  snapshots are not thereby erased.
- No migration, live bulk change, purge, DHIS2 refresh, credentialed sign-in, commit or push.
  No upstream DHIS2 request was made. No secret, token, dump or raw identifying line list was
  printed or included in this report.
- Live queries ran inside explicitly read-only PostgreSQL transactions with bounded statement
  timeouts. The application was not restarted; ports 8010 and 3100 remained in use.
- Tests used separately named disposable databases **only on port 55432**, not `hpip_live` or
  ports 5432/5433. Audit databases were removed after each test; their fixtures can recreate them.
  The pre-existing disposable server was left running. No live data was removed.
- Counterexample populations, counts and TEST_ONLY identifiers are isolated regression fixtures,
  not Uganda measurements or new production configuration. None was inserted into `hpip_live`.

The reproducible audit harness is `.local/audit20261011/test_independent_audit.py`. It leaves
correctness assertions failing rather than marking defects xfail or weakening expectations.
Other audit harnesses there perform read-only state/profiling and an anonymous login-page smoke.

## Section 4: all nine audit items

| Item | Verdict | Evidence obtained by running / limitation |
|---|---|---|
| 1. Memo input completeness | **Fail** | Both SQLite and PostgreSQL retained wrong malaria availability/numbers after coverage changed. PostgreSQL also returned ANC1 40% when a fresh calculation was 20% after an interleaved fingerprint/row-read sequence. |
| 2. MPDSR event-state detector | **Fail** | Actual overlapping PostgreSQL transactions changed a death cohort without changing count/min/max state. Cached maternal reviews remained 3; a fresh calculation gave 2. |
| 3. District-rows-only D-074 | **Qualified; approval still needed** | Live metadata has no formula version explicitly setting `require_all_components=false`. Comparing current and previous committed cohort resolvers kept the tested required composite unavailable. However its quality label changed BLUE → N/A as well as its reason. No exhaustive numerical-invariance proof for all historical/configurable formulas is claimed. |
| 4. Scoped yearly rebuild | **Fail under concurrency; stable-data checks pass** | New coverage rebuilt the correct unit to 110; removing coverage retired that year. Inconsistent nested/outer manifest units were rejected. But a concurrent normal month replacement was skipped and an obsolete 120 total labelled current despite current months summing to 209. |
| 5. Statement triggers | **Pass for tested DML; static scope limited** | One update of two rows bumped the global counter once; a zero-row update did not. Static search found no routine application/script TRUNCATE or destructive DDL path. TRUNCATE/DDL remain outside this change detector; this is not a proof about arbitrary administrator SQL. |
| 6. Bulk duplicate persistence / withdrawal | **Pass in reproduced duplicate case** | Two accepted occurrences yielded `stored=2`, one distinct seen ID and one last-occurrence current snapshot. Reconciliation withdrew only the genuinely unseen old event. The metric counts accepted observations, not distinct events. |
| 7. More than one local scheduler | **Fail** | Two scheduler instances reading the same fixture store both decided to spawn. Child spawning was mocked: no refresh actually started. Code has neither a cross-process scheduler claim nor an atomic scheduled-job insertion guard. |
| 8. Quality-scan reuse | **Fail for clock-sensitive freshness** | Twenty minutes after a scan, the source crossed the stale threshold, but the same run still skipped scanning. A fresh scan produced a stale flag on both databases. This concerns warnings, not a changed numerical formula. |
| 9. Parallel Tracker client | **Qualified, with a paging defect** | The two-peer test preserved peer order, serialised cancellation checks and restored the callback. A server-reported smaller page size stopped retrieval early and reported no truncation. The shared retry counter is also last-writer state, not a trustworthy aggregate retry count (code review; no retry-count race reproduced). |

## Wrong-number and stale-result reproductions

### F1 — concurrent monthly refresh can leave a wrong yearly total (high)

Location: `backend/app/services/period_rollup.py:204`, especially the fingerprint/scope decision at
243–263; subsequent batch revision capture in `backend/app/services/calculation.py:230`.

Inputs: one unit has twelve months of 10, so its materialised FY total is 120 and its roll-up
state has been verified. An unrelated period changes, causing re-verification. Immediately after
`_unit_digests` reads the unchanged year, another physical connection retires the first monthly
row and inserts its normal replacement with value 99. The scope is decided from the earlier
fingerprint and is empty.

Observed: report `status=current`, `created=0`; stored year **120**; sum of current month rows
**209**. A calculation batch taken afterward captured the newer revision while that stale year
was still current. This uses normal retire-and-insert source replacement, not editing the old
source row's value.

A later call to roll-up verification can repair it, but that is insufficient assurance for the
current request. Prepared-product logic can sign products at the revision captured after roll-up
verification (`prepared_dashboard.py:106`); the annual verification and calculation must share a
coherent input generation. Prepared-snapshot propagation here is a code-path inference, not a
browser reproduction of this specific concurrent race.

### F2 — the acknowledged coverage gap affects real supported indicators today (high)

Locations: `calculation.py:493` (Python fingerprint), `calculation.py:644` (database digest),
`calculation.py:671` (memo), `calculation.py:1101` (partial-cohort coverage checks).

The live registry enables D-067 reporting-unit policy for **MV1_COVERAGE, MV2_COVERAGE,
MV3_COVERAGE, MV4_COVERAGE and MV1_MV4_DROPOUT**. All five were independently exercised in both
databases, in both change directions.

Fixture: population 1,000,000; one reporting district supplies MV1/2/3=4,300 and MV4=2,150;
other peers have no dose rows. Complete month/key/unit coverage initially permits coverage
10/10/10/5% and dropout 50%. Invalidating that coverage left those cached numbers available;
a fresh calculation was unavailable. Conversely, a queued coverage job becoming succeeded
without any source-row change left cached unavailability, while a fresh calculation gave those
valid numbers. The latter is an ordinary completion transition, not an administrator-only edit.

Therefore the gap can change what is published, not just lineage or performance. A rebuilt view
or export backed by the reused run can inherit it. No intentionally failing experiment was run
against actual Uganda source data; this does not establish that today's five displayed national
values are already wrong.

The similar MPDSR reporting-unit versions exist in metadata but their gate is **false** in the
live configuration. They must not be enabled to bypass unavailable denominators. If later
approved, their aggregate-reporting components also require coverage in the fingerprint.

### F3 — taking a fingerprint before rows is not a complete safety proof (high)

Locations: `calculation.py:288`, `calculation.py:630`, `calculation.py:644`, `calculation.py:671`.

Fixture: ANC1=10,000, population=1,000,000 and the existing 5% target coefficient. The database
digest reads A=10,000. An actual second connection commits B=20,000 before the source rows load.
The result is 40%, but its memo stores A's digest. The source is subsequently restored to A in
place, preserving row identity/checksum/extraction identity. Re-verification matches A's digest
and returns that **40%** run; the fresh calculation gives **20%**.

This is an A→B→A reproduction involving in-place data corrections. Ordinary append-only ingestion
often changes row IDs and will defeat this particular A→B→A match. Nevertheless, the stated
unconditional proof is false: the stamp and calculated evidence came from different database
states. Configuration/fingerprint reads and inputs must belong to one stable snapshot/generation.

### F4 — min/max/count is not a complete event change detector (high)

Location: `calculation.py:402`.

Fixture: three retained completed maternal-review events in the cohort. Transaction T1 starts;
later T2 updates another event and commits, establishing the maximum `updated_at`. A run stores
count 3. T1 then moves a different event's death date outside the FY and commits. PostgreSQL's
`now()` for T1 is its earlier transaction time, so the maximum stays T2's timestamp; count,
oldest extraction and maximum creation time also stay unchanged.

Observed: event-state digest unchanged; memo returns **3**; fresh result **2**. Normal Tracker-job
status/manifest changes may independently invalidate this digest, and this experiment deliberately
kept the job set unchanged. It proves the event detector is incomplete, not that every successful
Tracker refresh currently returns stale values. A complete mutation revision or semantic per-row
digest is needed instead of relying on extrema.

### Other reproduced issues

- `tracker.py:108–115`: requested page size 2, response pager pageSize 1, with a second event on
  page 2. Only page 1 was requested; one event returned; `page_limit_reached=false`. This conditional
  response-contract defect can undercount and certify absence incorrectly. It is **not** evidence
  that Uganda's live server capped this job or that the 79,567 observation total is truncated.
- `local_scheduler.py:100`, `dhis2_refresh.py:160`: no cross-process claim before spawning;
  scheduled idempotency selection then insertion is not atomic. This matters before multi-process
  deployment or overlapping restarts, even though localhost currently uses eager operation.
- `calculation.py:736`, `modules.py:474`, `prepared_dashboard.py:82`: clock-only stale warnings can
  be delayed by the one-hour scan window; the non-event six-hour prepared lifetime can prolong
  cached warning state. Numerical values need not change for this warning to become outdated.

## Live state — verified read-only

Observed on 11 October, queries between 12:08 and 12:21 Africa/Kampala:

- `hpip_live` revision **0020_config_revision**.
- Tracker job `ee901d6b-e34d-44e4-a122-7937d91253c4` started **11:10:49.626**, succeeded
  **12:02:41.372**: **3,111.746 seconds / 51 min 51.746 sec**.
- Received/stored **79,567** observations, rejected **0**, page-cap flag false, manifest complete.
  Stored retry counter 1 is not necessarily a total retry count across parallel peers.
- **79,566** current retained event snapshots; **4,118** lack a usable death date. The one-count
  difference is consistent with duplicate-observation semantics; I did not compare every upstream
  UID, so do not present that as a complete upstream reconciliation.
- FY2025/26 prepared national figures now include perinatal notifications **16,676**, perinatal
  reviews **15,356**, maternal notifications **395**, maternal reviews **919**. These are actual
  stored live-data values, not regression fixtures or independently re-counted DHIS2 totals.
- Reported-death aggregate counts and workflow/timeliness coverage measures remain unavailable
  with `incomplete_children`. The job's success does not supply missing aggregate denominator
  rows or approve D-069. The whole MPDSR module is no longer blank, but it is not wholly assessable.
- The queued aggregate job from 24 September and running facility job from 10 October remain.

### Physical retention is not operational

The table contains **213,134** Tracker snapshots, including **133,568** older than the approved
24-hour cutoff. The oldest extraction is 25 September. None of those expired rows is current,
but they still exist in the restricted event store. Runtime controls: `PURGE_ENABLED=true`,
`PURGE_SCHEDULE_ENABLED=false`, `SYNC_EXECUTION=eager`.

Read exclusion is not deletion. The purge policy itself targets expired rows regardless of
currentness (`purge.py:292`). The local scheduler refreshes but does not schedule that purge.
This is an operational privacy/retention gap. I did not purge or clean any flag; approved backup
and verified dump must precede a bulk change.

The claim that `recover_sync_dispatch.py` fixes the abandoned running facility job is incorrect:
recovery is disabled in eager mode and selects unstarted queued/publication-failure jobs only
(`sync_recovery.py:23–35`). It deliberately excludes this running, started job. Abandonment needs
an explicit safe lifecycle/restart policy, not merely invoking that command.

## Browser gate and independent checks

Ran the requested `npm.cmd run e2e` without changing configuration or assertions. **Exit 1**:

```
port 8010 is already accepting connections before the run
port 8010 is still accepting connections
Playwright JSON report was not written by this run
```

No build, owned server or Playwright process was launched. The new layout and complete sign-in
journey therefore **have not passed this gate**. This is a preflight/environment-contract failure,
not an observed failing browser assertion.

Additionally, `e2e-gate.mjs:35,60` and `playwright.config.ts:25` hard-code web port 3000 instead of
the project's 3100. I did not occupy or stop the unrelated application port, stop the live API,
rewrite tests to pass, or run a synthetic E2E API as the owner's live system. Fix the test topology
only after approval and agree a safe acceptance window or allowed isolated topology.

An additional anonymous headless Chrome smoke on **3100/login** measured DOM readiness **0.301s**,
hydrated/enabled form **0.699s**, zero page errors; blank submission showed the client validation
message and sent **zero POST requests**. This verifies that narrow behaviour, not a credentialed
five-second sign-in, ready dashboard, full layout or all twenty screens.

## Timings and remaining performance

Read-only measurements of the actual prepared-product service, using the existing system-admin
scope and saved products (no calculations, login, refresh or new snapshots):

| National view | Prepared lookup | JSON serialization | Raw JSON size |
|---|---|---|---|
| ANC, default FY | 0.053–0.101s | 0.032–0.035s | 2.48 MB |
| Immunisation, default FY | 0.218–0.228s | 0.153–0.161s | 10.09 MB |
| MPDSR, default FY | 0.072–0.076s | 0.040–0.043s | 3.25 MB |

All nine tested module/period combinations had ready products. These are service timings in an
audit process, **not HTTP transfer, authenticated browser interaction or hundred-user results**.
Gzip is already enabled (`main.py:98`): equivalent level-6 compression produced approximately
86.5 KB for ANC, 348 KB for immunisation and 86.6 KB for MPDSR. Compression took approximately
0.05–0.06s, 0.20–0.24s and 0.06–0.07s respectively. Do not confuse 10 MB uncompressed with
10 MB on the wire; it still means sizeable client parsing/objects and repeated serialization.

The remaining measured long wait is the refresh/startup outage: today's Tracker work took about
52 minutes, during which retained MPDSR was unavailable. The newest extraction timestamp was
12:01:56.666, approximately 45 seconds before job completion; from the persistence call site's
timestamp placement, most elapsed time preceded bulk persistence. This stage attribution is an
inference, not a new instrumented upstream profile. Its cause is not proven to be "working hours".

Cold national 20–60s, cold MPDSR ~160s, previous query counts and full sign-in ~5s remain Claude's
measurements. I did not provoke live cold writes merely to reconfirm them. Code inspection confirms
uncached views still compute on request and preparation does not cover every region/period.
Hundred-user capacity, real Redis/Beat, full downloads and full layout acceptance are unverified.

## Verification ledger and unsupported claims

- Final independent experiments: **42 cases, 28 failing correctness assertions, 9 passes,
  5 skips, 0 setup/errors**, 109.26s. All five skips are SQLite variants of PostgreSQL-specific
  experiments; the PostgreSQL variants ran. The 28 failures are repeated cases of seven defect
  categories, not 28 different bugs. Do not reclassify them as environment failures.
- Existing selected suites (`test_postgres_fast_paths.py`, `test_run_reuse.py`,
  `test_mpdsr_minimisation.py`): **18 passed**, 37.58s. They do not cover the counterexamples.
  The two existing PostgreSQL cases migrated the disposable verification DB to head.
- Ruff (`app tests scripts alembic --no-cache`) passed. Final `git diff --name-only` was empty;
  only this report and the pre-existing Codex handoff were untracked. Local `origin/main` and
  HEAD both resolved to `e932d47`; no network fetch/push was performed.
- Claude's full 939/37 backend, 34 PostgreSQL and 97 frontend totals, build and all-screen/download
  walkthrough were not independently rerun in full. Their earlier success is not disproved by
  this audit, but is not proof that these defects are absent.
- "No value ever comes from changed inputs" is disproved by F1–F4.
- "Fingerprints before reads force every later check to fail" is disproved by the A→B→A case.
- "D-074 changes only a missing reason" omits the BLUE → N/A change. No live optional formulas
  were found, so an optional-component numerical change is not alleged to be active today.
- The three-year extraction is now completed, superseding the handoff's previously unknown outcome.
- Clean tree at audit entry, automatic physical retention and abandoned-running-job recovery
  must not be claimed on the observed state.
- Native FY aggregate requests contrary to D-057 remain in `_recent_periods`
  (`dhis2_refresh.py:50–58`). Six current native non-KMC FY2026/27 count rows were observed; this
  proves that path remains, not that an entire displayed national year is numerically wrong.

## What to fix first, after approval

1. **Coherent calculation/roll-up generations.** Bind yearly verification, source/reference
   fingerprints and material reads to one stable database snapshot or immutable committed input
   generation. Do not bless an old year at a newer calculation revision. Do not stamp digest A on
   result B. Preserve deterministic lineage and add the real concurrent replacement/A→B→A cases.
2. **Coverage and complete event change identity.** Put effective coverage jobs/manifests into
   both run fingerprint paths for reporting-unit formulas. Replace event extrema as sole identity
   with a complete semantic digest or dedicated mutation revision, retaining exact clock expiry.
   Avoid unnecessarily disabling all useful caching; correctness comes before warm speed.
3. **Physical retention and safe job lifecycle.** After approved verified backup, coordinate the
   existing purge with successful refresh, handle abandoned started work safely, and audit old
   flags. Do not shorten D-057 aggregate history or silently erase saved evidence. Atomically guard
   scheduled jobs / take a cross-process claim before adding API processes.
4. **Paging, metrics and freshness.** Respect effective server paging semantics, fail incomplete
   retrieval visibly, aggregate retries safely, and expire warning state at clock-sensitive
   thresholds rather than assuming unchanged rows imply unchanged quality.
5. **Acceptance and cold performance.** Repair the gate's port contract without weakening any
   assertion, run it in an authorised isolated setup, then time real cold/warm sign-in and exports.
   Profile quality scans/flushes/roll-up verification; prewarm commonly used regional views and
   coalesce same-view preparation. Compact presentation payloads while fetching complete pinned
   provenance on demand. Test the hundred-user requirement on an approved representative setup.

Keep D-069 blocked without approval and request confirmation of D-074 including its quality-label
effect. Existing national populations/UID approvals were not missing or requested again. No new
clinical rule, population or mapping is required to fix these cache/transaction defects.

**No implementation fix has been applied.** This report and ignored audit harnesses are the only
new audit artifacts; build-signature files and the live stack are unchanged.

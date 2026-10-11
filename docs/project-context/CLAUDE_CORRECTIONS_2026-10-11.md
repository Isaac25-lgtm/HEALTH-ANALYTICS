# Corrections after the independent audit (2026-10-11, afternoon)

Codex audited the speed work of 10 and 11 October and reproduced four ways it could return a stale
or wrong result, plus several smaller defects ([CODEX_AUDIT_2026-10-11.md](CODEX_AUDIT_2026-10-11.md)).
The owner instructed "fix". This file records what was wrong, what was changed, how each change is
tested, and what is still open. It supersedes the parts of
[CLAUDE_HANDOFF_2026-10-11.md](CLAUDE_HANDOFF_2026-10-11.md) listed in section 4.

No database migration was needed. `hpip_live` stays at `0020_config_revision`.

## 1. The four serious findings

| Finding | What was wrong | Correction |
|---|---|---|
| F1: a yearly total marked current while a month changed | The roll-up check fingerprinted the months, then decided, and a change committed in between was not seen. The calculation batch then read its revision after the check, so the stale year was read, and could be stamped, at the newer revision. | `ensure_period_rollups` repeats its pass until the revision is the same after the pass as before it and the pass wrote nothing, and reports the revision it reached. The batch is "coherent" only if that is the revision it is stamped with. An incoherent batch still answers the request, but nothing from it is remembered or signed (D-076). |
| F2: malaria vaccine results ignored extraction coverage | For reporting-units indicators (MV1 to MV4 coverage and dropout, D-067) a synchronisation finishing or being cancelled changes the result without changing a source row. Coverage was in neither fingerprint. This gap predates the October work and was carried into it. | The synchronisations able to certify a unit the run reads are hashed into both fingerprints for such indicators (`_coverage_digest`, D-077). A facility load for another district is not among them, so it does not disturb a national result. |
| F3: a result could carry a fingerprint of other data | The database fingerprint was read before the rows. A change between the two reads left a run made from state B holding the fingerprint of state A. | Nothing is stamped unless the revision is unchanged when the stamps are written (`flush_run_memos`). A run calculated while the revision moved also loses its reuse key, so the older input fingerprint cannot revive it either. |
| F4: the MPDSR change check could miss a change | It used the count, oldest extraction and newest timestamps of the retained events. A transaction that began earlier can commit later without moving any maximum. | The check hashes every retained event's own content (`_retained_event_digest`): computed by PostgreSQL in one query (not timed on the live data); hashed in Python on SQLite. |

## 2. The smaller findings

| Finding | Correction |
|---|---|
| Paging could stop early when the server serves smaller pages than requested | A page ends retrieval only when it is shorter than the page size the server reports. |
| Two API processes could both start a refresh | The scheduler takes a lease in the database (`maintenance_locks`) before starting one; exactly one process gets it. |
| A source turning stale was not re-scanned within the hour | A quality scan is reused only if no row in the run's scope has crossed the staleness limit since the scan, and never across a date change. A prepared product now also expires at the moment one of its rows turns stale, and at the month change. |
| An interrupted "running" job blocked the same request for ever, and the recovery script named in the handoff does not handle it | `reclaim_abandoned_sync_jobs` marks a facility load or scheduled job as failed ("interrupted") when it has been running for ten minutes and no process holds its execution lock. The scheduled refresh now holds that lock while it runs, so a live job is never touched. PostgreSQL only. |
| Expired MPDSR events are excluded but not deleted | When `PURGE_SCHEDULE_ENABLED=true`, the local scheduler now starts the existing governed purge about once a day. It is off by default and adds no deletion rule. **133,568 expired event rows remain stored; removing them is the owner's decision (section 5).** |
| Facility comparison runs were never remembered | `_facility_comparisons` now writes its stamps, under the same guard. |

## 3. A defect of my own that the audit did not reach

`test_concurrent_dashboards_do_not_cross_contaminate` failed in two of four full runs. Cause: on
SQLite a transaction that reads and then writes can deadlock with another writer, and SQLite fails
one of them at once ("database is locked"). The roll-up state row added on 10 October made every
dashboard request read and then write early. PostgreSQL is not affected, so the live system was
not, but tests and CI use SQLite. A dashboard request on SQLite now takes the write lock before it
reads. Under deliberate heavy load: failing before, eight of eight after.

This is very probably why the backend CI job failed on commit `e932d47`. CI logs are not public, so
that is an inference from reproducing it locally.

## 4. Statements in the 11 October handoff that were wrong

- "No value is ever taken from a result whose inputs changed." Disproved by F1 to F4. True only
  with the corrections above, and only as far as the tests in section 6 show.
- "`scripts/recover_sync_dispatch.py` exists for this" (the interrupted facility job). It does not
  handle a started job and is disabled in eager mode.
- D-074 "changes only the reason wording". It also changes the quality label from BLUE to N/A in
  that edge case. The decision register is corrected. Owner confirmation is still needed.
- "DHIS2 is slower in working hours." Both days were a weekend; the slowness is real, its cause is
  not established.
- The working tree was described as clean while the Codex handoff file itself was untracked.

## 5. Still open

1. **CI has been red since 24 September**, which no handoff reported, including mine.
   Jobs failing on GitHub, from the public run summaries (logs need a login):
   - Playwright: failing since `ca8cec7` (24 September, the rebuild toward the reference screens),
     and its layout checks still asserted the old one-screen rule. In this commit the gate's ports
     are configurable (`E2E_WEB_PORT`, `E2E_API_PORT`; defaults unchanged) and the desktop checks
     follow D-070. **The gate has not been run with these changes**, so other failures from
     September may remain.
   - Containers: failing since `d07ac8f` (5 October) at "build and start". Production
     configuration validates and the API and worker import cleanly with the compose environment,
     so configuration is ruled out. Not reproduced: there is no Docker on this workstation.
   - Backend tests: failed on `e932d47`; see section 3.
2. **Expired MPDSR events (133,568 rows)** are still physically stored. To remove them: take and
   verify a backup, then either run `python scripts/purge_expired.py --policy mpdsr_events` once,
   or set `PURGE_SCHEDULE_ENABLED=true` so the scheduler does it daily. Not done: it is a bulk
   deletion and needs the owner's word.
3. **D-074** awaits owner confirmation, including the BLUE to N/A effect.
4. **A first view after a data change** is still calculated on demand. The corrections add a little
   to that path (a second roll-up pass when the first rebuilt something; the event digest).
5. The retry counter of the DHIS2 client is "last writer wins" across parallel requests. It is a
   diagnostic number only and was left as it is.
6. Native financial-year aggregate requests contrary to D-057, old open quality flags, Redis,
   Celery Beat, hundred-user load: unchanged from the earlier lists.

## 6. Verification

- Codex's own audit harness (`.local/audit20261011/test_independent_audit.py`): 37 passed, 5
  skipped (SQLite twins of PostgreSQL-only cases), 0 failed. It had 28 failing assertions before.
- The same cases are now permanent tests in `tests/test_cache_coherence_audit.py`, with one more
  for interrupted jobs. PostgreSQL-only cases use their own fixture, because CI fails on any skip.
- The CI-like full backend run (PostgreSQL enabled) had not finished when this was committed; its result is not known.
- Frontend: TypeScript and ESLint clean after the gate changes. Vitest was last run before them
  (97 passed) and no application source changed since. The Playwright gate was not run.
- Not done at commit time: restarting the local stack on the corrected code and timing it. The
  running local API still has the previous code in memory; `start-local.ps1` loads the new code.

Changing `calculation.py`, `period_rollup.py`, `prepared_dashboard.py`, `dashboard.py` and
`analysis.py` invalidates every stored result by design. After the restart the API prepared the
common views again in the background.

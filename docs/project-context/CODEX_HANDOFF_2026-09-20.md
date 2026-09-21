# Codex handoff — national completion audit, 2026-09-21

This is an execution handoff for Claude. Start from repository HEAD `f4db75d` and preserve the
current uncommitted working tree. The owner asked for a Uganda-wide live platform, not a Pader demo.
Do not replace, reset or discard these changes, and do not apply unapproved hierarchy, source,
population or boundary records.

## Outcome and truth boundary

The application and configured DHIS2 account are not Pader-scoped analytically. The account's
capture scope is Pader, but its data-view root is `MOH - Uganda`. A bounded non-sensitive BCG query
for June 2025 returned 146 district/city rows; their sum was 158,721, exactly the national root
value. Pader was 600 (0.38%). The DHIS2 API works and national read access is proven.

The local dashboard is empty because governed production configuration is still absent: no
approved national hierarchy mappings, no approved 48-key formula source mapping set, no applied
or approved population version, and no activated geometry. The owner-supplied population workbook
has been staged but not promoted. Empty values must remain unavailable; never turn them into zero,
demo data or guessed mappings.

## Changes in the current working tree

1. **National and permission context**
   - System administrators receive all active programme scopes and land deterministically at `UG`.
   - `/me/context` exposes authorised geography levels and one safe entry unit per reachable level.
   - Sidebar geography and programme links are capability-aware and keep geography, period,
     comparison and module state. URL state still cannot expand server permissions.

2. **Periods and user actions**
   - The default is the latest closed Uganda July–June financial year. On 2026-09-20 that is
     `FY2025/26`, compared with `FY2024/25`; `FY2026/27` is labelled in progress.
   - Options are derived from the current financial year, so the default does not become stale in
     later calendar years.
   - Recalculate uses already governed source rows. `Refresh from DHIS2` is a separate action.

3. **Safe server-owned refresh**
   - `POST /sync/refresh` accepts internal geography, period and module only. It never accepts a
     DHIS2 UID or mapping version from the browser.
   - The server requires `manage_sync`, geography and programme access, selects exactly one
     complete in-force mapping version and refuses incomplete or ambiguous coverage before a job
     exists. MPDSR remains blocked pending approved event semantics.
   - The generic aggregate job route now applies the same formula-source coverage preflight.

4. **Queue lifecycle and cancellation**
   - Queue dispatch is centralised. A conditional update durably claims queued work before network
     I/O; duplicate deliveries do not run the same job twice.
   - Production PostgreSQL workers hold a dedicated per-job advisory lock for the full execution.
     If a worker dies, its connection releases the lock and a redelivery can reclaim the persisted
     `running` row. SQLite eager/test mode retains the conditional status guard.
   - Celery uses late acknowledgement and worker-loss rejection. Unexpected exceptions persist a
     safe `internal_sync_error`; no exception detail is stored. Cancellation is a permission- and
     scope-checked server endpoint, and active extraction re-reads cancellation state.

5. **Honest empty states and exports**
   - Dashboard snapshots distinguish configuration blockers from data-quality alerts. No-source
     snapshots show zero quality notifications instead of fabricated alerts.
   - Facility catchment wording is limited to facilities. Higher levels state that an approved
     governed population version is missing.
   - Empty snapshots disable export actions, and the export service independently rejects them
     with `export_no_verified_data`.
   - Administration cards load actual control-store counts from `/ops/status`.

6. **Governed application of approved packets**
   - `app/services/governed_imports.py` and `scripts/apply_governed_packet.py` separate evidence
     proposals from configuration.
   - Hierarchy/source packets require their approval schema, an exact non-empty approval reference,
     every row marked approved, two different active users with `manage_mappings`, valid dates and
     collision-free records. The command checks the Alembic head and is all-or-nothing/audited.
   - `--check` executes validation and rolls the transaction back. Partial source sets remain
     visibly incomplete and cannot refresh a programme.

7. **Database concurrency guard**
   - Alembic head is now `0013_org_mapping_guard`. On PostgreSQL it installs `btree_gist` and an
     exclusion constraint preventing overlapping validity intervals for one source-system/UID.
     SQLite retains application validation.

8. **Render and operations**
   - `render.yaml` declares `DHIS2_LOGIN_ENABLED=false`, `DHIS2_AUTH_METHOD=basic`, and secret slots
     for a dedicated DHIS2 integration identity on API and worker. Flags remain off until approvals
     and supervised validation.
   - The in-process operational event buffer is bounded. `/ops/status` reports real hierarchy,
     mapping, staging, population, boundary, formula, job and freshness counts.

9. **Final DHIS2 scope, period and category corrections**
   - Uganda sync is fail-closed unless the active hierarchy contains exactly 146 district/city
     peers and each peer has exactly one effective, unique DHIS2 UID. A single mapped district can
     no longer run under a national label. Regional scopes require all district/city peers; a leaf
     requires its own mapping.
   - Aggregate Analytics receives explicit peers with `ouMode=SELECTED`; Tracker queries those
     non-overlapping peers with `DESCENDANTS` so lower-level events are not omitted.
   - Native DHIS2 response periods are normalised back to the requested HPIP period. `AVERAGE` and
     `LAST` mappings use complete monthly inputs and remain unavailable when required months are
     absent. Event Analytics requests also use DHIS2-native period IDs.
   - Category-specific mappings request the exact documented `DE.COC` operand. The response parser
     recovers the data-element and category-combo IDs, and governance rejects a category combo on
     an indicator mapping.

## Local PostgreSQL changes already made

- Before mutation, a custom-format logical backup was written to the ignored path
  `backend/.local/backups/hpip-pre-completion-20260920-203912.dump` (208,016 bytes).
- The dedicated local `hpip_live` database was upgraded successfully from revision 0012 to 0013.
- The supplied workbook checksum remained
  `5AE43DCA4533347FBB95C3F9B4E08A25C953C90905445614BA7D4E4BD3E75072`.
- All 1,022 district/city-year cells were staged as batch
  `7393d637-3d8d-4106-9fde-b5a30eb9515f`.
- All remain unmatched because the local store intentionally has only the neutral `UG` root.
  Zero population versions/values were created; no denominator was approved.

No raw DHIS2 performance row, MPDSR event, boundary, source mapping or sub-national production
hierarchy was applied by Codex.

## Final verification completed by Codex

- Ruff over `backend/app`, `backend/tests`, `backend/scripts`: clean.
- Focused connector/governance/national regression set: **62 passed**.
- Full backend on SQLite: **841 passed, 32 skipped, 0 failed** in 17m15s. The skips are the
  PostgreSQL-only and Redis integration tests.
- Frontend TypeScript / ESLint: clean / clean.
- Frontend Vitest: **111 passed** across 10 files.
- `npm run build`: exit 0; all dashboard and workspace routes built.
- `npm run e2e`: **24 passed, 0 skipped, 0 flaky**. Playwright exited by itself; the gate stopped
  its API and web processes, found no survivors, freed ports 3000/8010 and proved the pre-existing
  dirty worktree was unchanged. A first run also had all 24 tests pass but failed closed because
  the owner opened Firefox during the run; baseline-delta mode did not terminate that unrelated
  browser. The second run included it in the baseline and passed.
- `git diff --check`: no whitespace errors (only Windows LF-to-CRLF notices).
- The persistent local PostgreSQL migration 0012 → 0013 succeeded earlier. It is not a disposable
  test database and was not used for destructive tests.
- This restricted account could not start the disposable PostgreSQL 18 cluster (`pg_ctl` restricted
  token error 87 / start error 3). The new PostgreSQL migration and advisory-lock concurrency tests
  exist but still need execution by Claude's owner-capable account. Redis remains unavailable.

## Claude's verification and correction, 2026-09-21

The PostgreSQL path Codex could not execute contained a real defect, now fixed.

- **Migration `0013_org_mapping_guard` could not be downgraded.** `downgrade()` called
  `op.drop_constraint(..., type_="exclude")`, but Alembic's `generic_constraint` accepts only
  `check`, `foreignkey`, `primary`, `unique` or `None`, so the call raised
  `KeyError: 'exclude'` → `TypeError`. `test_postgres_downgrade_is_explicit` and
  `test_postgres_upgrade_after_downgrade` both failed on the first owner-capable run. The
  downgrade now issues explicit `ALTER TABLE org_unit_mappings DROP CONSTRAINT IF EXISTS
  ex_org_mapping_no_overlap`, symmetric with the raw DDL the upgrade uses. No other change was
  made to the migration, and the exclusion constraint itself was already correct.

Recorded totals from this workstation (owner-capable account):

| Gate | Result |
|---|---|
| Ruff over `app tests scripts` | clean |
| Backend, SQLite | **841 passed, 32 skipped, 0 failed** (12m47s) |
| Backend, disposable PostgreSQL 18 on port 55432 | **871 passed, 2 skipped, 0 failed** (13m29s) |
| PostgreSQL migration suite alone, after the fix | **15 passed** |
| Frontend TypeScript / ESLint | clean / clean |
| Vitest | **111 passed** across 10 files |
| `npm run build` | exit 0, all dashboard and workspace routes |
| `npm run e2e` | **24 passed, 0 unexpected, 0 skipped, 0 flaky**; Playwright exited by itself, no survivors, ports 3000/8010 freed, tree fingerprint unchanged |

The two remaining skips are **only** `tests/test_redis_integration.py:28` and `:46`. Neither Redis
nor Docker is installed on this workstation, so they are reported as skipped, never as passed. CI
executes them.

Two artifacts owned by the Codex account blocked this run and were moved aside rather than
deleted, which is the route `scripts/prepare-build-dir.mjs` itself recommends:
`frontend/.next` → `.build-quarantine/next-20260921-121303`, and
`frontend/test-results` → `.build-quarantine/test-results-20260921-124316` (Playwright failed with
`EPERM ... unlink test-results/.last-run.json` until it was moved). `.build-quarantine/` is
gitignored and awaits owner removal.

No hierarchy, source mapping, population version or boundary was applied during this work.

## Commands rerun before committing

```powershell
cd backend
C:\Users\USER\AppData\Local\Programs\Python\Python312\python.exe -m ruff check app tests scripts
C:\Users\USER\AppData\Local\Programs\Python\Python312\python.exe -m pytest -q -p no:cacheprovider --basetemp=.local\pytest-claude-final

cd ..\frontend
C:\Program Files\nodejs\npm.cmd run typecheck
C:\Program Files\nodejs\npm.cmd run lint
C:\Program Files\nodejs\npm.cmd test -- --run
C:\Program Files\nodejs\npm.cmd run build
```

Use a **disposable** PostgreSQL 18 cluster/database for the full PostgreSQL suite, with
`HPIP_POSTGRES_TEST_URL`; never point those tests at `hpip_live`. The suite already contains the
two-connection overlap test and the advisory-lock duplicate/reclaim test: run them, do not recreate
them. Run the real-Redis tests if a disposable Redis is available. Then run `npm run e2e` with
installed Chrome if ports 3000 and 8010 are free. Confirm the gate leaves no child process, ports
or working-tree mutation.

## Owner/Ministry decisions still blocking real national values

These cannot be repaired in code or guessed. Use
`docs/project-context/OWNER_APPROVAL_PACKET.md` as the decision sheet.

- D-A: provision/approve a dedicated Uganda-wide read-only service identity and rotate the
  disclosed personal password. The present account proves UAT reach but must not be hosted.
- D-B: decide how live DHIS2 level 4 (DLG/Municipality/City Council) maps into HPIP.
- D-C: approve or reject exactly three aliases: Luweero/Luwero, Ssembabule/Sembabule, and Kampala
  Capital City/Kampala District.
- D-E/F: approve boundary effective dates/references and decide whether the sub-county map may
  activate with 16 missing live units and duplicated OBJECTID 1240.
- D-G/H: clinically approve all required source keys and category detail. `ROTAV1` and `ROTAV2`
  have no candidate, and the current account cannot see 53 category option combinations.
- D-I: approve effective dates for the 60 formula versions, or explicitly authorise the undated
  fallback for UAT only.
- D-J: define MPDSR dates, linkage, cause taxonomy and minimum disclosure cell count.
- Approve EPI bands, official Ministry crest/templates, monitoring/alerting, backup/restore test,
  and Render/Neon resources before production sign-off.

## What Claude should do next

1. Review every uncommitted diff against this handoff and the canonical project documents. Keep
   the national scope and fail-closed rules above.
2. Run the existing PostgreSQL concurrency tests proving two connections cannot overlap one
   external UID and that a locked duplicate is rejected while a row left `running` can be
   reclaimed after lock release. Do not weaken existing assertions.
3. Run the complete SQLite/PostgreSQL/frontend/build/E2E gates described above. If this sandbox
   cannot delete or execute an owned artifact, report the exact path and perform only the necessary
   operation from the owner-capable account.
4. Do not contact DHIS2 again merely to repeat discovery. Do not enable scheduled refresh, and do
   not convert proposal JSON into an approval packet without named owner/clinical decisions.
5. When all code-controlled checks pass, update this handoff with exact totals, commit the complete
   working tree, push `master` to `origin/main` by fast-forward only, and verify the remote SHA.
6. Restart localhost from the committed code only after the final build/gate. Report the API/web
   PIDs, `/health`, `/ready`, `/login`, and whether the displayed dashboard remains correctly
   blocked on governed data. Never describe an empty but honest dashboard as live data-ready.

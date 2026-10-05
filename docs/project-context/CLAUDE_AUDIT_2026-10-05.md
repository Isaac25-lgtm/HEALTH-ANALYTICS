# Claude audit of the combined working tree — 2026-10-05

Scope: independent verification of Codex's corrections (`CODEX_CORRECTIONS_2026-10-02.md`,
`CODEX_FIX_HANDOFF_2026-10-05.md`) plus the operator steps the owner authorised ("do everything",
then narrowed to "audit and commit; report shortcomings"). No application code was changed in this
audit. Findings are reported, not fixed.

## 1. Test evidence on the exact committed tree

| Check | Result |
|---|---|
| Backend full suite (SQLite, private `--basetemp`) | **930 passed, 0 failed, 35 skipped** (33 PostgreSQL-only, 2 Redis) |
| PostgreSQL suites on a disposable 18.x cluster (port 55432, never `hpip_live`) | **55 passed, 0 failed, 0 skipped**, incl. migration 0015 upgrade/downgrade/re-upgrade, model parity, revision triggers, and the two new two-connection races (facility queue, dispatch recovery) |
| Ruff `app tests scripts --no-cache` | Clean |
| Frontend TypeScript / ESLint | Clean |
| Frontend Vitest (app tests) | 96 passed; full serial run incl. process-gate tests previously 115 passed on an unchanged frontend |
| `npm run build` in the real checkout | Passed (earlier on 2026-10-03; no frontend source change since) |
| Redis/Celery worker, Beat scheduler, restart recovery | **Not verified** (no Redis on the workstation) |

Note: 136 "errors" in a first backend run were not code failures; a sandbox account had made
pytest's shared temp folder unreadable. Rerunning with a private temp folder passed.

## 2. Operator steps performed (owner instruction "do everything", 2026-10-05)

1. Backup `C:\Users\USER\hpip-backups\hpip_live_20261005_092925_pre_0015.dump` (463 MB), verified
   with `pg_restore --list` (299 entries, 45 table-data entries incl. raw aggregate values).
2. `alembic upgrade head` on `hpip_live`: 0014 → **0015** applied; `analytics_revisions` created,
   51 revision triggers installed. Reference bootstrap: no drift, nothing created.
3. API (127.0.0.1:8010, `WEB_ORIGIN=http://localhost:3100`) and web (`next start -p 3100`) started.
4. Supervised GET-only DHIS2 refresh via `scripts/dhis2_refresh.py`: 12 aggregate jobs (MNCH, EPI,
   MPDSR × Aug–Oct 2026 and FY2026/27) all **succeeded with complete coverage manifests**. The MPDSR
   Tracker job (FY2025/26–FY2026/27 through today) was still running when this audit was committed.
5. Not performed (owner narrowed scope to audit + commit): dashboard warming
   (`scripts.prepare_dashboards`), historical re-extraction with manifests, audited flag cleanup.

## 3. Measured behaviour on the live local store (browser, real sign-in)

| Step / view | First visit (cold) | Repeat (warm) |
|---|---|---|
| Sign-in until identity shown ("Signed in as ISAAC OMODING (biostat.pader)") | 7.1 s | — |
| Sign-in until landing dashboard opens | **155 s** | — |
| National ANC FY2025/26 | 47.7 s | **2.5 s** |
| National immunisation Jun 2026 | 96.1 s | **2.6 s** |
| Pader district FY2025/26 | 33.6 s | **2.0 s** |
| Acholibur sub-county FY2025/26 | 33.2 s | — |
| Downloads (Excel, PowerPoint, PDF, Word) from national view | 2.3–3.3 s each, all succeeded | — |

Conditions: first cold run after the code change and migration (every earlier run fingerprint is
invalid), while the MPDSR Tracker extraction ran on the same machine. Cold numbers are therefore
worst-case, but they are real.

## 4. Shortcomings found (not fixed)

1. **Cold loads remain slow.** 33–96 s per new view; sign-in waits up to 155 s for the landing
   dashboard. Warm repeats (2–2.6 s) show the prepared-snapshot mechanism works, but nothing is
   warm until someone visits or `scripts.prepare_dashboards` runs. The "enter only when ready"
   sign-in moves the cold wait onto the sign-in screen, as predicted.
2. **Sign-in hydration race.** Typing before the login page finishes hydrating submits empty
   fields; the API answers 422 (invalid credentials format). The browser audit hit this once.
3. **`scripts/dhis2_refresh.py` has no dry-run.** Running it without `--scheduled` performs the real
   extraction; `--scheduled` only labels the run. Operator hazard (it started this audit's refresh
   earlier than intended).
4. **Native long-period aggregate requests persist.** The refresh extracts `FY2026/27` natively
   alongside months, contrary to the monthly-source contract (D-057) — already listed by Codex.
5. **Long DHIS2 jobs run inside the web server process locally** (eager execution). Facility loads
   for Pader and Acholibur stayed "running" for the whole audit while the Tracker job ran; the
   facility banner correctly kept saying "Loading…", but the user waits indefinitely with no ETA.
6. **MPDSR currency not yet re-established.** The two-year Tracker extraction runs longer than an
   hour; retention is 24 h. Without a worker/scheduler the cache will expire again.
7. **Old noisy flags remain open:** MISSING_CAUSE 17,314; POSSIBLE_DUPLICATE_EVENT 5,169;
   REVIEW_INTERVAL_OUT_OF_RANGE 4,198; STALE_REPORTING 3,210; ACTIVE_MPDSR_WORKFLOW 2,055;
   MISSING_CRITICAL_DATE 1,894; others smaller. New false positives are prevented; cleanup pending.
8. **Coverage manifests exist only for the months refreshed today.** Older months cannot certify
   non-reporting, so districts with a missing month keep that year's total unavailable until a
   governed re-extraction records coverage.
9. **Redis worker, scheduler and dispatch recovery are untested and switched off.**
10. One browser console 404 for a static resource on each page (cosmetic).
11. Owner decisions still open: D-069 (blocked by default), facility catchment populations,
    facility coordinates, MPDSR cause taxonomy/disclosure, production formula effective dates.

## 5. Verdict

Codex's corrections are real and well tested; every runnable suite passes, including the
PostgreSQL proof Codex could not obtain. The system is a working local UAT build on live data with
fast repeat views, not a production-ready platform: cold performance, background execution, MPDSR
operation and alert hygiene remain open.

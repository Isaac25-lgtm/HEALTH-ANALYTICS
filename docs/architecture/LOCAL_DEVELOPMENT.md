# Local development and tests

## Persistent live-DHIS2 local UAT

Do not use `scripts/run_e2e_api.py` for live work; it deliberately recreates SQLite and seeds
synthetic users and observations. Configure the persistent PostgreSQL-backed local environment
interactively instead:

```powershell
cd backend
python scripts/configure_live_local.py --dhis2-username <provisioned-dhis2-user>
python -m alembic upgrade head
python scripts/bootstrap_reference_data.py
python scripts/create_initial_admin.py --username <same-user> --identity-provider dhis2 --no-prompt
python scripts/dhis2_discovery.py --resource me --resource system-info --confirm-network-access --out .local/dhis2/capability.json
```

The setup command reads both passwords without echo and writes them only to the root `.env`, which
Git ignores. It creates no synthetic geography, mappings, population or performance values. Rotate
any credential disclosed in a transcript before hosted use. Discovery proves connectivity only;
source and organisation-unit mappings still require review before the first bounded sync.

Additional real staff must be pre-provisioned with explicit HPIP authorisation before they can
sign in with their DHIS2 credentials. Their password is not supplied to this command:

```powershell
cd backend
python scripts/provision_dhis2_user.py --username district.user --display-name "District User" --role district_mch_focal --org-unit-code PADER --programme MNCH
```

The organisation unit must already be in the approved HPIP hierarchy. Repeat `--role`,
`--org-unit-code`, or `--programme` when needed. MPDSR requires the additional
`--allow-sensitive-mpdsr` acknowledgement; this command cannot grant system administration.

## Prerequisites

- Python 3.12
- Node.js 22+ (for the frontend shell)
- PostgreSQL 16+ recommended for shared local data; SQLite is used automatically by the test suite
- Docker Compose is optional (`docker-compose.yml`) when Docker is available

## Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev,worker]"
copy ..\.env.example .env
# Set AUTH_SECRET and, for local API use, SEED_DEV_DATA=true
python scripts/bootstrap_db.py
uvicorn app.main:app --reload --port 8000
```

Synthetic users (password from `SEED_PASSWORD`):

| Username | Landing geography | Programmes | Notes |
|---|---|---|---|
| `national.analyst` | Uganda | MNCH, EPI, MPDSR | view + export + AI report |
| `acholi.analyst` | Acholi | MNCH, EPI, MPDSR | cannot see Teso or national |
| `pader.focal` | Pader | MNCH | can edit population |
| `paderhc3.user` | Pader HC III | MNCH | view only |
| `mnch.only` | Uganda | MNCH | export allowed; EPI/MPDSR denied |
| `view.only` | Uganda | MNCH, EPI, MPDSR | cannot export |
| `mpdsr.analyst` | Acholi | MPDSR | event view; no line-list export |
| `admin.user` | Uganda | all | includes `manage_users` |

## Frontend

```powershell
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`. The login form is blank. A synthetic development run uses the explicitly seeded test users; persistent live-DHIS2 UAT uses an explicitly pre-provisioned DHIS2 identity. Unknown DHIS2 accounts are never auto-created. The browser calls the same-origin `/api/*` path and Next.js proxies it to `BACKEND_INTERNAL_URL` (default `http://127.0.0.1:8000`), so cookies always belong to the page's own origin.

Local development without Redis must opt in explicitly in `.env`: `RATE_LIMIT_BACKEND=memory`, `EXPORT_EAGER=true`, `SYNC_EXECUTION=eager`. With a local Redis, set the broker URLs, keep `EXPORT_EAGER=false` and start a worker:

```powershell
celery --app=app.workers.celery_app:celery_app worker --queues=exports,sync,maintenance --pool=solo
```

For isolated tests, DHIS2 stays off and sync jobs fail with `dhis2_not_configured`. The interactive live-UAT setup at the top of this document enables DHIS2 and never seeds fabricated observations.

## Tests

From `backend/`:

```powershell
pytest
ruff check app tests alembic scripts
```

SQLite is used by the default suite. PostgreSQL tests run only when `HPIP_POSTGRES_TEST_URL` names a disposable cluster; there is no default server, so the suite never tries to log in to a workstation instance. They create and drop only `hpip_p18_alembic_verify`. On this workstation the disposable PostgreSQL 18.1 cluster lives in `backend/.grok-pg18-verify` (port 55432, trust authentication, local only):

```powershell
& 'C:\Program Files\PostgreSQL\18\bin\pg_ctl.exe' start -D backend\.grok-pg18-verify -w
$env:HPIP_POSTGRES_TEST_URL = 'postgresql+psycopg://hpip@127.0.0.1:55432/postgres'
pytest -q -rs --basetemp C:/hpt/run   # short base path: long temp paths exceed the Windows path limit
& 'C:\Program Files\PostgreSQL\18\bin\pg_ctl.exe' stop -D backend\.grok-pg18-verify
```

Never point that variable at the instances on ports 5432/5433. Real-Redis tests run when `HPIP_REDIS_TEST_URL` is set (CI). `HPIP_FAIL_ON_SKIP=1` turns any skip into a failure.

Tests use mocked DHIS2 HTTP and `TEST_UID_*` fixtures. See `docs/architecture/SYNTHETIC_FIXTURES.md`.

Frontend:

```powershell
cd frontend
npx tsc --noEmit
npm run lint
npm test
npm run build
npm run e2e
```

ESLint 9 and `eslint-config-next@15.5.25` are installed with the lockfile. The build uses the standard `frontend/.next` directory.

### Locked build output on Windows

Next.js 15.5.25 clears `.next` at the start of `next build` and retries `EPERM` forever, so output written by another OS account makes the build hang after the version banner. `npm run build` runs `scripts/prepare-build-dir.mjs` first: it performs that clean-up with bounded retries and, if files are locked, exits with the exact paths and the owner command. Do not work around it by changing `distDir`.

### Playwright

The disposable end-to-end API seeds the demonstration dataset described in
`SYNTHETIC_FIXTURES.md`, so local screens render populated, coloured dashboards rather than empty
states. It is development/test only and refuses to run anywhere else.

`npm run e2e` and `npm run e2e:gate` use the bounded acceptance runner (`scripts/e2e-gate.mjs`;
lifecycle logic in `scripts/e2e-gate-lib.mjs`, tests in `scripts/e2e-gate-lib.test.mjs`, run by
`npm test`). It first creates a production build without a backend address (an owned, sampled
child bounded by 900 seconds), then directly owns the disposable API
(`backend/scripts/run_e2e_api.py`, port 8010), the production Next server (port 3000, runtime
`host:port` backend), and Playwright. Direct ownership avoids Playwright's shell-based Windows
teardown, which may be denied on restricted accounts.

The gate fails on a non-zero/flaky/skipped test, a missing or stale JSON report, a post-summary exit
over 60 seconds, 90 seconds of pre-summary inactivity, a 600-second Playwright runtime, an owned
process that cannot be started (missing executable, access denied or any other spawn error), an
owned process that will not stop, an occupied service port, unavailable, failing or timed-out
process verification (each process-table query is bounded by 20 seconds and only the gate's own
lister child is stopped on timeout), an owned process whose identity cannot be verified, a
surviving process, or a working-tree change. Every failure still runs bounded cleanup, prints the
JSON summary and exits non-zero.

The initial process inventory is a prerequisite, not merely a reported check. If it is unavailable,
the gate records `execution_started: false` and exits without running build preparation or starting
the build, API, Next server or Playwright. After an executed run, survivor detection repeatedly
rechecks for up to five seconds rather than deciding from one timing-sensitive snapshot. Persistent
survivors still fail the run and, in parent-tree mode only, are revalidated before termination.

Working tree: a pre-existing dirty tree is permitted. The gate records `git status --short` and a
SHA-256 fingerprint of the binary diff against `HEAD` plus every untracked file's bytes before the
run, and requires both to be identical afterwards, so rewriting an already-modified file is also
detected. `working_tree_clean_before` in the summary only reports whether the run started clean; it
is not a pass condition. An explicit evidence refresh excludes `docs/evidence/screenshots/` only.

Process attribution: parent-tree enumeration is preferred. Each owned process is identified by PID
plus creation time, captured immediately after spawning and accepted only if the row is within the
declared timestamp allowance of the spawn and the process is still running after the query. Windows
tables use millisecond resolution. Unix `ps lstart` prints whole seconds and, on Linux, derives the
value from a second-resolution boot time plus jiffies; the effective pre-spawn allowance is therefore
two seconds. Descendants are attributed
only through a live owned root whose current table row matches that exact identity, so an exited or
reused root PID never attributes anything. The walk visits each PID once and rejects a child created
before its supposed parent, or with an unknown creation time. Survivors attributed this way are
matched again by PID and creation time in a fresh query before being terminated, after the failure
is recorded. Restricted Windows uses a PID/start-time baseline-delta check, which cannot attribute
processes to the run and therefore never terminates anything. `npm run e2e:raw` retains
Playwright's built-in web-server lifecycle for diagnostics, but it is not the acceptance command.

Vitest runs test files serially because the real-process gate tests intentionally inventory Node and
browser processes. Parallel Vitest workers created after a restricted-Windows baseline would be
indistinguishable from gate-created processes in baseline-delta mode and correctly produce a
fail-safe false positive.

Ordinary runs write screenshots to ignored `test-results/visual-evidence/` (volatile snapshot IDs
and timestamps masked). Refresh tracked evidence in `docs/evidence/screenshots/` only with
`npm run e2e:evidence` (`UPDATE_VISUAL_EVIDENCE=1`). CI uses Playwright-managed Chromium; locally,
set `HPIP_PYTHON` and optionally `HPIP_BROWSER_EXECUTABLE` (for example the installed Chrome).
Authentication is cookie-only; the frontend must not store an access token.

## Migration history

Fresh databases upgrade empty → `0013_org_mapping_guard` (head), followed by `python scripts/bootstrap_reference_data.py` for the reference configuration (or `scripts/bootstrap_db.py` with `SEED_DEV_DATA=true` for synthetic development data). A database at any earlier revision upgrades forward in order; revisions 0001–0008 are frozen. Do not assume a shared database can be deleted. Revision 0004 adds programme scope to raw aggregate uniqueness and enforces one open-ended current geometry per organisation unit; revision 0013 adds the PostgreSQL concurrency guard for overlapping DHIS2 organisation-unit mapping intervals. Reconcile pre-existing conflicting rows before upgrading.

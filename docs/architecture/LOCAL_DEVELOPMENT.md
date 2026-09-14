# Local development and tests

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

Open `http://localhost:3000`. The login form is blank; sign in with a synthetic user above. The browser calls the same-origin `/api/*` path and Next.js proxies it to `BACKEND_INTERNAL_URL` (default `http://127.0.0.1:8000`), so cookies always belong to the page's own origin.

Local development without Redis must opt in explicitly in `.env`: `RATE_LIMIT_BACKEND=memory`, `EXPORT_EAGER=true`, `SYNC_EXECUTION=eager`. With a local Redis, set the broker URLs, keep `EXPORT_EAGER=false` and start a worker:

```powershell
celery --app=app.workers.celery_app:celery_app worker --queues=exports,sync,maintenance --pool=solo
```

DHIS2 is switched off (`DHIS2_ENABLED=false`). Sync jobs fail with `dhis2_not_configured`; that is expected and no live call is made.

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
pytest -q -rs
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
npx playwright test
```

ESLint 9 and `eslint-config-next@15.5.25` are installed with the lockfile. The build uses the standard `frontend/.next` directory.

### Locked build output on Windows

Next.js 15.5.25 clears `.next` at the start of `next build` and retries `EPERM` forever, so output written by another OS account makes the build hang after the version banner. `npm run build` runs `scripts/prepare-build-dir.mjs` first: it performs that clean-up with bounded retries and, if files are locked, exits with the exact paths and the owner command. Do not work around it by changing `distDir`.

### Playwright

Playwright starts the disposable API (`backend/scripts/run_e2e_api.py`, port 8010) and a production Next server whose `/api` proxy points at it (`BACKEND_INTERNAL_URL`). It writes `playwright-report/results.json` and screenshots to `e2e-screenshots/`; `node scripts/assert-no-skips.mjs playwright-report/results.json` fails on skipped or missing tests. CI uses Playwright-managed Chromium; locally, set `HPIP_PYTHON` and optionally `HPIP_BROWSER_EXECUTABLE` (for example the installed Chrome). Server reuse is opt-in (`HPIP_REUSE_E2E_SERVER=true`) so runs do not strand processes. Authentication is cookie-only; the frontend must not store an access token.

## Migration history

Fresh databases upgrade empty → `0011_population_import_staging` (head). A database at any earlier revision upgrades forward in order; revisions 0001–0008 are frozen. Do not assume a shared database can be deleted. Revision 0004 adds programme scope to raw aggregate uniqueness and enforces one open-ended current geometry per organisation unit; reconcile pre-existing duplicate current rows before upgrading. Revision 0005 adds export file metadata and AI request columns.

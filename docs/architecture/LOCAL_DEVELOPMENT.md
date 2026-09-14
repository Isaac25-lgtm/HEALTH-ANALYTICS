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
pip install -e ".[dev]"
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

Open `http://localhost:3000`. After login the UI opens the highest authorised dashboard. The frontend default API base is `http://localhost:8000` so session cookies are not split across `localhost` and `127.0.0.1`.

Sync jobs fail with `dhis2_not_configured` until authorised `DHIS2_BASE_URL` and credentials are supplied. That is expected.

## Tests

From `backend/`:

```powershell
pytest
ruff check app tests alembic scripts
```

SQLite is used by the default suite. PostgreSQL Alembic tests run when `HPIP_POSTGRES_TEST_URL` is reachable. They create and drop only `hpip_p18_alembic_verify`. Do not point that variable at a shared database you do not intend to use as an admin connection.

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

ESLint 9 and `eslint-config-next@15.5.25` are installed with the lockfile. The production build writes to `frontend/.next-build` to avoid a Windows lock on a leftover `.next` directory. Playwright starts a disposable API on port 8010 and rebuilds Next with `NEXT_PUBLIC_API_BASE_URL=http://localhost:8010` so the browser does not call an unrelated process on port 8000. Authentication is cookie-only; the frontend must not store an access token.

## Migration history

Fresh databases upgrade empty → `0005_phase567_ai_publishing`. A database already stamped at 0002 applies 0003 then 0004 then 0005; a corrected database at 0004 applies only 0005. Do not assume a shared database can be deleted. Revision 0004 adds programme scope to raw aggregate uniqueness and enforces one open-ended current geometry per organisation unit; reconcile pre-existing duplicate current rows before upgrading. Revision 0005 adds export file metadata and AI request columns.

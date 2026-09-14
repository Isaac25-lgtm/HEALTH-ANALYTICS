# Environment variable reference

All values below are placeholders. Do not commit real secrets. Copy `.env.example` to `.env`.

| Variable | Purpose |
|---|---|
| `APP_ENV` | `development`, `test`, `staging`, or `production` |
| `DATABASE_URL` | SQLAlchemy URL. PostgreSQL required outside local tests. |
| `AUTH_SECRET` | JWT signing secret; at least 32 characters |
| `AUTH_TOKEN_TTL_MINUTES` | Session cookie lifetime |
| `AUTH_COOKIE_NAME` | HTTP-only session cookie name (`hpip_session`) |
| `AUTH_COOKIE_SECURE` | Set true behind HTTPS |
| `AUTH_COOKIE_SAMESITE` | Cookie SameSite policy (`lax` default) |
| `AUTH_CSRF_COOKIE_NAME` / `AUTH_CSRF_HEADER_NAME` | CSRF cookie and matching header |
| `AUTH_ISSUER` / `AUTH_AUDIENCE` | JWT `iss` / `aud` |
| `LOGIN_MAX_ATTEMPTS` / `LOGIN_WINDOW_SECONDS` | Login throttle |
| `POPULATION_YEAR_MIN` / `POPULATION_YEAR_MAX` | Accepted catchment/population years |
| `SYNC_EXECUTION` | `queue` (production) or `eager` (tests only) |
| `SEED_DEV_DATA` | Seed synthetic users; must be false in staging/production |
| `SEED_PASSWORD` | Password for synthetic development users |
| `WEB_ORIGIN` | Allowed CORS origin for the frontend |
| `DHIS2_BASE_URL` | Connector base URL. Owner-supplied text is approximately `HMIS.hhs.go.ug`. Exact host is unverified. |
| `DHIS2_USERNAME` / `DHIS2_PASSWORD` | Basic-auth credentials when `DHIS2_AUTH_METHOD=basic` |
| `DHIS2_PAT` | Personal access token when `DHIS2_AUTH_METHOD=pat` |
| `DHIS2_AUTH_METHOD` | `basic` or `pat` |
| `DHIS2_API_PATH_PREFIX` | Version-compatible API prefix, default `/api` |
| `DHIS2_TIMEOUT_SECONDS` | Request timeout |
| `DHIS2_MAX_RETRIES` | Bounded retry count for transient errors |
| `DHIS2_RETRY_BASE_SECONDS` / `DHIS2_RETRY_MAX_SECONDS` | Exponential backoff bounds |
| `DHIS2_PAGE_SIZE` / `DHIS2_MAX_PAGES` | Pagination limits |
| `DHIS2_MAX_RESPONSE_BYTES` | Response size bound |
| `DHIS2_OU_MODE` | Organisation-unit mode, default `DESCENDANTS` |
| `DHIS2_STALE_HOURS` | Freshness window used by quality rules |
| `REDIS_URL` | Cache / broker |
| `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` | Required when `SYNC_EXECUTION=queue` and Celery workers are used |
| `HPIP_POSTGRES_TEST_URL` | Optional SQLAlchemy URL for PostgreSQL Alembic tests |
| `AI_PROVIDER` / `AI_BASE_URL` / `AI_API_KEY` / `AI_MODEL` / `AI_ENABLED` | AI Gateway; disabled unless enabled with a key and base URL |
| `AI_TIMEOUT_SECONDS` / `AI_MAX_TOKENS` / `AI_PROMPT_VERSION` / `AI_MAX_EVIDENCE_CHARS` / `AI_RATE_LIMIT` | Gateway bounds |
| `EXPORT_DIR` / `EXPORT_RATE_LIMIT` | Publishing artifact directory and per-user rate limit |
| `NEXT_PUBLIC_API_BASE_URL` | Frontend API origin, default `http://localhost:8000`; keep the hostname aligned with the frontend so cookie auth works |

# Environment variable reference

All values below are placeholders. Do not commit real secrets. Copy `.env.example` to `.env`.

| Variable | Purpose |
|---|---|
| `APP_ENV` | `development`, `test`, `staging`, or `production` |
| `DATABASE_URL` | SQLAlchemy URL. PostgreSQL required outside local tests; on Neon, the pooled connection string. Plain `postgresql://` is normalised to `postgresql+psycopg`. |
| `MIGRATION_DATABASE_URL` | Optional direct (unpooled) URL that Alembic prefers for DDL |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | Per-process pool (defaults 5/5; production rejects a total above 20) |
| `DB_POOL_RECYCLE_SECONDS` / `DB_POOL_TIMEOUT_SECONDS` / `DB_CONNECT_TIMEOUT_SECONDS` / `DB_POOL_PRE_PING` | Connection hygiene |
| `DB_SSLMODE` / `DB_REQUIRE_SSL` | `require` for managed PostgreSQL; `DB_REQUIRE_SSL=false` only for a private network you control |
| `AUTH_SECRET` | JWT signing secret; at least 32 characters |
| `AUTH_TOKEN_TTL_MINUTES` | Session cookie lifetime |
| `AUTH_COOKIE_NAME` | HTTP-only session cookie name (`hpip_session`) |
| `AUTH_COOKIE_SECURE` | Set true behind HTTPS |
| `AUTH_COOKIE_SAMESITE` | Cookie SameSite policy (`lax` default) |
| `AUTH_CSRF_COOKIE_NAME` / `AUTH_CSRF_HEADER_NAME` | CSRF cookie and matching header |
| `AUTH_ISSUER` / `AUTH_AUDIENCE` | JWT `iss` / `aud` |
| `LOGIN_MAX_ATTEMPTS` / `LOGIN_WINDOW_SECONDS` | Login throttle |
| `POPULATION_YEAR_MIN` / `POPULATION_YEAR_MAX` | Accepted catchment/population years |
| `SYNC_EXECUTION` | `queue` (production) or `eager` (development/test only) |
| `SEED_DEV_DATA` | Seed synthetic users; must be false in staging/production |
| `SEED_PASSWORD` | Password for synthetic development users |
| `WEB_ORIGIN` | Allowed CORS origin for the frontend |
| `DHIS2_ENABLED` / `SYNC_ENABLED` | Both default false. While false, discovery and refresh commands contact nothing and readiness reports DHIS2 as `disabled`. Enabling without complete configuration is a blocking error. |
| `DHIS2_BASE_URL` | Known host `https://hmis.health.go.ug` (D-049). Credentials, mappings and live access are not verified. |
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
| `REDIS_URL` | Distributed rate limiting. No default; required in staging/production. |
| `RATE_LIMIT_BACKEND` | `redis` (default) or `memory` (per-process, development/test only and only when set explicitly) |
| `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` | No default; required in staging/production. `memory://` is refused outside development/test. |
| `EXPORT_QUEUE_NAME` / `SYNC_QUEUE_NAME` / `MAINTENANCE_QUEUE_NAME` | Celery queues (`exports`, `sync`, `maintenance`); one worker consumes all three |
| `EXPORT_EAGER` | In-request export generation; permitted only when set explicitly in development/test |
| `EXPORT_MAX_ATTEMPTS` / `EXPORT_RETRY_BACKOFF_SECONDS` / `EXPORT_RETRY_BACKOFF_MAX_SECONDS` / `EXPORT_JOB_LEASE_SECONDS` | Bounded worker retries and stale-claim recovery |
| `EXPORT_ARTIFACT_STORAGE` / `EXPORT_SHARED_FILESYSTEM` / `EXPORT_ARTIFACT_MAX_BYTES` | `filesystem` (shared disk) or `database` (Render); size cap |
| `RAW_AGGREGATE_RETENTION_DAYS` / `MPDSR_EVENT_RETENTION_HOURS` / `EXPORT_FILE_RETENTION_HOURS` / `EXPORT_JOB_RETENTION_DAYS` / `CALCULATION_SNAPSHOT_RETENTION_MONTHS` / `AUDIT_LOG_RETENTION_MONTHS` | Retention windows (7 d / 24 h / 24 h / 90 d / 36 months / 24 months) |
| `OPERATIONAL_RECORD_RETENTION_DAYS` | Maintenance run records and operational events (90 d; engineering default pending owner confirmation) |
| `POPULATION_HIERARCHY_APPROVAL_REFERENCE` | Reference to the owner's approval of the district/city hierarchy. Empty keeps every population crosswalk match a non-production candidate. |
| `PURGE_ENABLED` / `PURGE_DRY_RUN` / `PURGE_SCHEDULE_ENABLED` / `PURGE_BATCH_SIZE` / `PURGE_MAX_BATCHES` / `PURGE_LOCK_TIMEOUT_SECONDS` | Purge controls |
| `FORMULA_UNDATED_FALLBACK` | Whether undated legacy formula versions may be used; unset = development/test only |
| `MPDSR_CAUSE_MIN_CELL_COUNT` | Unset keeps cause patterns withheld |
| `HEALTHCHECK_HOST` | Host header the container healthcheck sends (one of `ALLOWED_HOSTS`) |
| `HPIP_REDIS_TEST_URL` | Optional disposable Redis for real-Redis tests (CI) |
| `HPIP_FAIL_ON_SKIP` | `1` makes any skipped backend test fail the run (CI) |
| `HPIP_ADMIN_PASSWORD` | Read once by `scripts/create_initial_admin.py`; never stored |
| `HPIP_POSTGRES_TEST_URL` | Optional SQLAlchemy URL for PostgreSQL Alembic tests |
| `AI_PROVIDER` / `AI_BASE_URL` / `AI_API_KEY` / `AI_MODEL` / `AI_ENABLED` | AI Gateway; disabled unless enabled with a key and base URL |
| `AI_TIMEOUT_SECONDS` / `AI_MAX_TOKENS` / `AI_PROMPT_VERSION` / `AI_MAX_EVIDENCE_CHARS` / `AI_RATE_LIMIT` | Gateway bounds |
| `EXPORT_DIR` / `EXPORT_RATE_LIMIT` | Publishing artifact directory and per-user rate limit |
| `BACKEND_INTERNAL_URL` | Read **at request time** by the `/api/[...path]` route. `http(s)://host[:port]` or a bare `host:port` (Render `hostport`, normalised to `http://`). Required in production (unset → HTTP 500 `proxy_misconfigured`); development falls back to `http://127.0.0.1:8000`. Not needed at build time and never exposed to the browser. |
| `E2E_BACKEND_HOSTPORT` | Playwright only: backend given to `next start` by `scripts/e2e-web.mjs` |
| `HPIP_PYTHON` / `HPIP_BROWSER_EXECUTABLE` / `HPIP_REUSE_E2E_SERVER` | Playwright: Python for the disposable API, optional local browser, opt-in server reuse |

# Deployment — Render + Neon UAT

This runbook prepares a small, secure UAT deployment for about 100 light users (decisions D-042 to D-049). **Nothing described here has been deployed**, no Neon database has been connected, and live DHIS2 is not authorised. Passing tests is not owner acceptance.

## Topology

| Component | Where | Notes |
|---|---|---|
| `hpip-web` | Render web service (`frontend/Dockerfile`) | Next.js. The browser calls same-origin `/api/*`; Next forwards it server-side to `BACKEND_INTERNAL_URL`. Session and CSRF cookies therefore belong to the web origin. |
| `hpip-api` | Render web service (`backend/Dockerfile`) | FastAPI. `preDeployCommand: alembic upgrade head` runs migrations before new code receives traffic. |
| `hpip-worker` | Render background worker (same backend image) | One Celery worker for `exports`, `sync` and `maintenance`, concurrency 2. |
| `hpip-redis` | Render Key Value | Celery broker, result backend and distributed rate limiting. `noeviction`, so queued jobs are never dropped. |
| `hpip-purge` | Render cron job | Daily at 01:30 UTC: `python scripts/purge_expired.py --source scheduler` — the same service as the Celery maintenance task. |
| `hpip-dhis2-refresh` | Render cron job | Six-hourly, **prepared but inert**: exits without contacting DHIS2 while `DHIS2_ENABLED`/`SYNC_ENABLED` are false. |
| PostgreSQL | **Neon** (external) | No Render PostgreSQL is provisioned. |

The blueprint is `render.yaml`. Check Render's current documentation for plan names, cron and Key Value behaviour before relying on them; the file records the intended shape, not verified provider limits.

## 1. Neon

1. Create a Neon project in a region close to the Render region you choose.
2. Create a database (for example `hpip`) and an application role with its own password. Do not reuse any workstation credential.
3. Copy two connection strings from the Neon console:
   - the **pooled** connection string → `DATABASE_URL` (runtime);
   - the **direct** connection string → `MIGRATION_DATABASE_URL` (DDL, only if migrations fail through the pooler).
4. Prefix both with `postgresql+psycopg://` and keep `sslmode=require` (or set `DB_SSLMODE=require`). Production validation rejects a non-TLS database unless `DB_REQUIRE_SSL=false` is set explicitly for a private network, which does not apply to Neon.
5. Keep the pool small. Defaults are `DB_POOL_SIZE=5` and `DB_MAX_OVERFLOW=5` per process. With the API, one worker, the migration command and the purge cron, the ceiling is about 40 connections; validation rejects a per-process total above 20.

Never paste a connection string into the repository, an issue or a log. The application does not log connection strings.

## 2. Render

1. Create a Blueprint from `render.yaml`. Render prompts once for every `sync: false` value.
2. Put the shared backend values in an environment group named `hpip-shared` (used by the worker and both crons): the same `DATABASE_URL`, `MIGRATION_DATABASE_URL`, `AUTH_SECRET`, Redis URLs, retention and feature switches as `hpip-api`.
3. Set `WEB_ORIGIN` and `ALLOWED_ORIGINS` to the `https://` URL of `hpip-web`, and `ALLOWED_HOSTS` to the API public host plus its internal hostname.
4. Leave `DHIS2_ENABLED=false`, `SYNC_ENABLED=false` and `AI_ENABLED=false`.
5. Export files use `EXPORT_ARTIFACT_STORAGE=database`, because Render services do not share a disk. Validation rejects `filesystem` storage when `EXPORT_SHARED_FILESYSTEM=false`.

## 3. Release

```bash
# Runs automatically as preDeployCommand; to run by hand from an API shell:
alembic upgrade head
alembic current            # expect 0011_population_import_staging (head)
python -c "from sqlalchemy import text; from app.db.session import get_engine; print(get_engine().connect().execute(text('SELECT 1')).scalar())"
```

The API and worker refuse to start in production when `validate_runtime_settings` reports a blocking error (missing broker, Redis, TLS, secrets, eager exports, per-process rate limiting, incomplete DHIS2 configuration when enabled). Development seed data is never created in production.

### First administrator

```bash
python scripts/create_initial_admin.py --username <name> --display-name "<full name>"
```

There is no default username or password. The password is read from a prompt (or `HPIP_ADMIN_PASSWORD`), never printed, and the command is audited and idempotent. MPDSR programme access is not granted automatically.

### Checks after release

- `GET /health` — process liveness.
- `GET /ready` — database, configuration, queue and Redis (no secrets). DHIS2 is reported separately as `disabled` and does not fail readiness.
- `GET /ops/status` (administrator) — worker ping, export job counts including permanent failures, retention and formula policy.
- Sign in through the web origin, run a dashboard query (CSRF POST), request an export and download it.
- From the API shell: `python scripts/queue_smoke.py --timeout 120` proves dispatch, consumption and results.

## 4. Retention and purge

| Data | Window | Setting |
|---|---|---|
| Raw aggregate cache | 7 days | `RAW_AGGREGATE_RETENTION_DAYS` |
| Minimised MPDSR event cache (with event UIDs) | 24 hours | `MPDSR_EVENT_RETENTION_HOURS` |
| Export files | 24 hours | `EXPORT_FILE_RETENTION_HOURS` |
| Export job metadata (terminal jobs) | 90 days | `EXPORT_JOB_RETENTION_DAYS` |
| Snapshots, runs, values, evidence | 36 calendar months | `CALCULATION_SNAPSHOT_RETENTION_MONTHS` |
| Audit log | 24 calendar months | `AUDIT_LOG_RETENTION_MONTHS` |

```bash
python scripts/purge_expired.py --show-policies     # current windows and cutoffs
python scripts/purge_expired.py --dry-run           # counts only; writes nothing
python scripts/purge_expired.py                     # purge, recorded in maintenance_runs
```

Purges are leased per policy, batched, idempotent and restartable. Queued and running export jobs are never purged by age; a snapshot still referenced by a retained export job is skipped until that job ages out. Records contain counts and safe codes only.

## 5. Backup and restore

Back up what cannot be re-derived: users, roles and scopes; indicator registry; population registry, staging batches and aliases; geography and mappings; compact snapshots, runs, values and provenance; audit; data-quality workflow; export job metadata.

Expired caches and export bytes are temporary by design and must not become a permanent archive. A logical backup can keep their schema but exclude their rows:

```bash
pg_dump "$MIGRATION_DATABASE_URL" --format=custom --no-owner \
  --exclude-table-data=raw_aggregate_values \
  --exclude-table-data=raw_event_snapshots \
  --exclude-table-data=export_artifacts \
  --file=hpip-$(date +%Y%m%d).dump
pg_restore --dbname "$TARGET_DATABASE_URL" --no-owner --clean --if-exists hpip-YYYYMMDD.dump
```

Neon also provides point-in-time restore; confirm the retention of that history matches D-043 before relying on it. Test a restore into a separate Neon branch before UAT sign-off.

## 6. Credential rotation

1. Create the new Neon role password (or Redis/DHIS2 secret) alongside the old one.
2. Update the value in Render (service or `hpip-shared` group) and redeploy the API, worker and crons.
3. Confirm `/ready`, then revoke the old credential.
4. Rotating `AUTH_SECRET` signs every user out; schedule it.

## 7. Local production-like stack

`docker-compose.yml` runs PostgreSQL, Redis, migrations, API, worker and web with **no usable default credentials** (`docker compose --env-file .env.production config -q` fails until every secret is set). Its PostgreSQL is a container on a private network, so it sets `DB_REQUIRE_SSL=false` explicitly. CI renders the compose file, builds images and runs the queue smoke test; Docker was not available on the development workstation, so that job has not been executed locally.

## Still required before production sign-off

DHIS2 credentials, verified metadata mappings and a supervised bounded validation; an approved organisation-unit hierarchy with alias decisions; boundary effective date; formula-version effective dates or an explicit undated-version decision; MPDSR date semantics; monitoring, alerting and a tested restore. See `docs/project-context/OPEN_ITEMS.md`.

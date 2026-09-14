# Sync and calculation operational runbook

## Sync jobs

`POST /sync/jobs` with a JSON body:

```json
{
  "org_unit_id": "<uuid>",
  "period": "202407",
  "programme": "MNCH",
  "job_type": "aggregate",
  "mapping_version": "v1",
  "idempotency_key": "optional-80-char-key"
}
```

`job_type` is the `ConnectorType` enum:

- `aggregate`
- `event_analytics_query`
- `event_analytics_aggregate`
- `tracker`

Unknown values return **422**. `programme` is an internal programme code. Client-supplied DHIS2 `program_uid` is rejected.

Requires `manage_sync`. Geography and programme are re-checked. System administrators may list all jobs; other users see only authorised geography and programme.

POST creates a `queued` job and returns **202**. A registered worker task (`app.workers.tasks.execute_sync_job`) performs retrieval and persistence.

- Production: `SYNC_EXECUTION=queue`. Celery must be installed and a worker must consume the `sync` queue. Live sync also requires `DHIS2_ENABLED=true` and `SYNC_ENABLED=true`, both currently false.
- Tests: eager execution when `APP_ENV=test` or `SYNC_EXECUTION=eager`.
- States: `queued`, `running`, `succeeded`, `partially_succeeded`, `failed`, `cancelled`.
- Cancellation is checked between pages/batches.
- Worker retries are bounded (`max_retries=3`) and stored on the job.
- Duplicate submissions reuse `idempotency_key` for the same user when supplied.
- Hitting the page cap cannot be presented as complete success.

When DHIS2 is not configured, jobs fail with `dhis2_not_configured` and the pending-verification message. That is expected in this workspace.

Inspect:

- `GET /sync/jobs`
- `GET /sync/jobs/{id}`
- `GET /sync/freshness`

## Calculation

`POST /calculations/run` with `{ org_unit_id, period, programme, indicator_codes? }`

`programme` is required. Requires `view` plus geography and that programme. Facility users cannot run a parent aggregate.

`GET /calculations/{runId}` re-checks geography and the stored programme.

Quality scan runs after a successful calculation.

## Observability

`operational_events` records connector duration, retry count, sync start/end, records received/stored/rejected, and calculation duration. Payloads are redacted.

Do not log passwords, tokens, session secrets, patient names, narratives, or unrestricted MPDSR payloads.

## Health

- `GET /health` — process liveness, `phase=phase-7`
- `GET /ready` — database + config; DHIS2 reported separately
- `GET /ops/status` — administrators only; no credentials
- SQLite backup helper: `python scripts/backup_restore.py` (refuses PostgreSQL URLs)

## Cancellation and bounds

Sync jobs honour `cancelled`. HTTP client enforces timeout, retry cap, page cap, Retry-After backoff, and max response bytes.

## One worker, three queues

A single Celery worker consumes everything this deployment needs:

```bash
celery --app=app.workers.celery_app:celery_app worker --queues=exports,sync,maintenance --concurrency=2 --loglevel=INFO --without-gossip --without-mingle
```

| Queue | Task | Retry and recovery |
|---|---|---|
| `exports` | `app.workers.tasks.generate_export_job` | Late acknowledgement; atomic claim per job; bounded by `EXPORT_MAX_ATTEMPTS` (3) with backoff; a claim older than `EXPORT_JOB_LEASE_SECONDS` can be taken over; duplicate deliveries are no-ops. |
| `sync` | `app.workers.tasks.execute_sync_job` | `max_retries=3`. Inert while DHIS2 is disabled. |
| `maintenance` | `app.workers.tasks.purge_expired_data` | Same purge service as the CLI and cron; per-policy lease; `max_retries=2`. |
| any | `app.workers.tasks.queue_health_probe` | Echo task used by `scripts/queue_smoke.py`. |

Checks: `celery --app=app.workers.celery_app:celery_app inspect ping`, `python scripts/queue_smoke.py`, and `GET /ops/status` (worker count, export jobs by status, permanent failures).

## Export failures

- Enqueue failure: the job is committed first, then marked `failed` with `export_enqueue_failed` (HTTP 503, `retryable: true`). Resubmitting the same export or `POST /exports/jobs/{id}/retry` re-dispatches the same job.
- Generation failure: work in progress is rolled back and `failed` is committed in a clean transaction with a safe `error_code`. Retries continue up to the limit; after that the job stays visible as a permanent failure and a new request creates a new job.
- Expired file: the download answers `410 artifact_expired` with the checksum; request the export again from the snapshot.

## Retention purge

Daily: `python scripts/purge_expired.py --source scheduler`. Use `--dry-run` first after any window change (it writes nothing). Each policy pass is recorded in `maintenance_runs`. `skipped_locked` means another purge process holds that policy; `failed` carries `purge_failed` and the exception class only.

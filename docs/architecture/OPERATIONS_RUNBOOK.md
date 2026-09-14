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

- Production: `SYNC_EXECUTION=queue` (default outside tests). Celery must be installed and a worker must consume the queue.
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

# Deployment

This document is the production runbook for a future hosting decision. It does not authorise a go-live against live DHIS2 or a shared PostgreSQL instance.

## Release checklist

1. Set `APP_ENV=production` or `staging`.
2. `DATABASE_URL` must be PostgreSQL. SQLite is rejected.
3. `AUTH_SECRET` must be a unique value of at least 32 characters, not the repository placeholder.
4. `AUTH_COOKIE_SECURE=true` behind HTTPS.
5. `SEED_DEV_DATA=false`. Do not use `SEED_PASSWORD=dev-only-change-me`.
6. `SYNC_EXECUTION=queue` with Redis/Celery if background sync is enabled.
7. Leave `AI_ENABLED=false` unless a reviewed key, base URL, and data-processing approval exist.
8. Run `alembic upgrade head` (current head: `0005_phase567_ai_publishing`).
9. Confirm `GET /health` and `GET /ready` and, as an administrator, `GET /ops/status`.
10. Confirm cookie/CSRF login from the approved web origin.

`validate_runtime_settings` encodes these checks. `/ready` reports remaining config errors without echoing secrets.

## Processes

- API: `uvicorn app.main:app` from `backend/` (or an ASGI equivalent).
- Web: `next start` with `NEXT_PUBLIC_API_BASE_URL` on the same cookie host as the API.
- Workers: Celery when `SYNC_EXECUTION=queue`.

## Backup and restore

- **SQLite (local/dev only):** `python scripts/backup_restore.py backup <source.sqlite> <backup.sqlite>`. The helper refuses PostgreSQL URLs.
- **PostgreSQL:** use the host's `pg_dump` / `pg_restore`. Do not point test helpers at a shared cluster. Do not write production passwords into the repository.

## Observability

- `GET /health` — liveness, phase `phase-7`
- `GET /ready` — database and configuration
- `GET /ops/status` — admin-only; no credentials
- `operational_events` and `audit_log` — no passwords, tokens, or MPDSR line lists

## What is still required before production sign-off

Verified DHIS2 URL and credentials, approved populations and boundary mappings, official publishing templates, identity provider, Redis/hosting/SLA, and MPDSR disclosure governance. These remain in `docs/project-context/OPEN_ITEMS.md`.

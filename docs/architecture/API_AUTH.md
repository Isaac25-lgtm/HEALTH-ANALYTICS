# API and authentication contract

Base URL (development): `http://127.0.0.1:8000`

Interactive OpenAPI: `/docs`

## Selected authentication approach

Same-origin browser authentication uses an **HTTP-only session cookie**. The raw access token is **not** returned in the JSON body and is **not** stored in `localStorage`.

```
POST /auth/login
{ "username": "<provisioned-user>", "password": "<password>" }
→ { "ok": true, "csrf_token": "..." }
Set-Cookie: hpip_session=<JWT>; HttpOnly; SameSite=Lax; Secure in production
Set-Cookie: hpip_csrf=<csrf>; SameSite=Lax; readable by the frontend
```

- JWT claims include `typ=access`, `iss`, `aud`, `jti`, `nbf`, `exp`.
- The server stores `auth_sessions` by JTI. Logout revokes the session.
- Mutating requests except `/auth/login` require `X-CSRF-Token` matching the CSRF cookie.
- Login is length-checked and throttled (`login_attempts` / `LOGIN_MAX_ATTEMPTS`).
- Default access lifetime is `AUTH_TOKEN_TTL_MINUTES` (120). Renewal is a fresh login in this phase; a refresh-token flow is not implemented.
- Passwords and tokens are not written to logs.
- Users with `identity_provider=dhis2` are pre-provisioned in HPIP, then their submitted password is
  checked against DHIS2 `/api/me` for that request only. HPIP stores the returned immutable subject,
  not the password. Local HPIP grants remain authoritative after authentication.
- Ordinary staff are provisioned with `scripts/provision_dhis2_user.py`, which requires explicit
  existing role, geography and programme scopes. It refuses implicit MPDSR access and cannot create
  a system administrator. Unknown DHIS2 users are never auto-created during login.

Bearer tokens in browser storage are not used. Tests send the CSRF header; the TestClient carries the HTTP-only cookie.

Synthetic seeded users exist only in the explicit development/test fixture. They are not created by the production reference bootstrap or the persistent live-UAT setup.

## Current context

```
GET /me/context
```

Returns the authenticated user, role codes, geography scopes, programmes, actions, and `landing_org_unit` (highest authorised organisational unit). System administrators land at country `UG`.

Inactive roles and inactive or expired geography/programme grants are ignored.

## Authorisation rules

Permissions remain geography × programme × action and are enforced on the server.

- `GET /org-units/{id}` and children/ancestors require `view` and geography membership (self or descendant).
- `GET /programmes` returns only first-release programmes in the user's programme scope.
- `GET /populations`, `GET /populations/resolve` require `view` and geography. `POST /populations/facility` requires `edit_population`. Approve/reject require `approve_population`. Ordinary editors cannot self-approve unless they are system administrators.
- `GET /indicators` and `GET /indicators/{id}/versions` require `view` and programme scope.
- `POST /calculations/run` requires `view`, geography, and a **mandatory** programme. Indicator codes are validated against that programme. An omitted programme is not “all programmes.”
- `GET /calculations/{runId}` re-checks geography **and** the stored programme. A known UUID does not bypass programme authorisation. Returned indicators are checked again against programme scope.
- `GET /quality/flags` filters authorised geography and programme in the database query. Ordinary responses use a redacted schema (no event UIDs, rare facility/date/cause combinations, names, narratives, or raw payloads). Sensitive flag detail requires MPDSR programme scope and `view_mpdsr_events`.
- `GET/POST /sync/jobs` and `GET /sync/jobs/{id}` require `manage_sync`. The body uses an internal programme **code**, not a client-supplied DHIS2 `program_uid`. `job_type` is an enum; unknown values return 422. List/get are scoped by authorised geography and programme unless the user is a system administrator. `event_window_end` is accepted for Tracker jobs only and must fall between the period end and today (`event_window_not_supported` / `invalid_event_window`). `GET /sync/freshness` reports the last successful job and `last_attempt` separately.
- `GET /mappings` and `GET /mappings/events` require `manage_mappings`.
- `POST /exports/excel|powerpoint|report` require `export` plus programme and geography scope and a matching `analysis_snapshot_id` + `view_hash`. `POST /exports/jobs/{id}/download` is owner-only and CSRF-protected because it writes an audit record; the former `GET …/file` route was removed.

## Analytical execution contract (amendment 2026-09-13)

Safe methods never create calculation runs, snapshots, quality flags or audit rows. A regression test replays every registered GET route against a file database and asserts the database is byte-identical.

| Route | Method | Effect |
|---|---|---|
| `/analytics/dashboard/query` | POST (CSRF) | Runs the calculation and commits one snapshot. Body: `org_unit_id`, `period`, optional `module`, `comparison_period`, `selected_indicator`, `request_key` (8–80 of `A-Z a-z 0-9 _ -`). Returns 201. Re-sending the same key for the same request returns 200 with the committed snapshot and `snapshot_reused=true`; a different request with the same key returns 409 `snapshot_conflict`. Keys are unique per user. |
| `/analytics/modules/{module}/query` | POST (CSRF) | Evaluates one module and commits its runs. Returns 201. |
| `/analysis-snapshots/{id}` | GET | Read-only. Owner-only (others get 404); `view`, geography and the snapshot module's programme are re-checked on each read. |
| `/analysis-snapshots/{id}/map-features` | GET | Read-only GeoJSON for exactly the snapshot's map cohort, with values copied from the snapshot. |

A failed execution rolls back: no runs, values, quality flags or snapshot remain. The browser keeps `request` and `snapshot` in the URL, so a page refresh re-opens the committed snapshot instead of recalculating; "Recalculate from current data" issues a new key.
- `GET /mpdsr/events` requires `view_mpdsr_events` and MPDSR programme scope. Raw payloads are not returned.
- `POST /exports/mpdsr-linelist` requires `export_mpdsr_linelist`.
- `POST /admin/probe` requires `manage_users` and writes an audit row.

Changing an organisation-unit UUID in the URL cannot expand access.

## Health

- `GET /health` — process liveness (`phase=phase-2`)
- `GET /ready` — database ping and configuration validation; `dhis2` is reported separately (`not_configured` or `configured_unverified`)

Typed contracts are in `backend/app/schemas/api.py`. OpenAPI remains at `/docs`.

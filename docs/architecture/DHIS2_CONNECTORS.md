# DHIS2 connector architecture

Phase 2 implements three separate adapters. Application services depend on typed observations, not raw DHIS2 JSON.

| Adapter | Module | DHIS2 family | Persistence |
|---|---|---|---|
| Aggregate Analytics | `backend/app/integrations/dhis2/aggregate.py` | `/api/analytics` | `raw_aggregate_values` |
| Event Analytics query | `backend/app/integrations/dhis2/event_analytics.py` | `/api/analytics/events/query/{program}` | `raw_event_snapshots` (`source_connector=event_analytics_query`) |
| Event Analytics aggregate | same | `/api/analytics/events/aggregate/{program}` | mapped into `raw_aggregate_values` |
| Tracker Events | `backend/app/integrations/dhis2/tracker.py` | `/api/tracker/events` | `raw_event_snapshots` (`source_connector=tracker`) |

Event Analytics and Tracker are never treated as one source. Freshness is stored independently on `freshness_snapshots`.

## Mapping selection

Aggregate mappings are filtered by authorised programme, enabled state, valid dates, requested mapping version, item kind, and category context. Event mappings are filtered by programme, programme stage, event type, valid dates, and mapping version. The platform does not build one UID-to-field dictionary from every programme. Ambiguous/colliding mappings fail with `MappingSelectionError`.

The sync API accepts an internal programme **code**. The server resolves the approved versioned mapping, including any DHIS2 programme UID. A client-supplied production `program_uid` is not accepted as job authority.

## Tracker retrieval

Tracker queries apply `occurredAfter` / `occurredBefore` from the selected period/cohort. Unbounded programme history is not retrieved. All authorised organisation-unit mappings are queried according to DHIS2 `ouMode` semantics (`DESCENDANTS` for a single root; `SELECTED` when multiple mapped units are queried). If `DHIS2_MAX_PAGES` is reached before completion, the job is marked partial/failed (`page_limit_reached`). Silent success is not allowed.

An empty `instances` list is a valid empty page, not a malformed payload.

## HTTP client

`Dhis2HttpClient` provides:

- environment-configured base URL and API path prefix (`DHIS2_API_PATH_PREFIX`, default `/api`);
- basic authentication or personal-access-token (`DHIS2_AUTH_METHOD=basic|pat`);
- request timeout;
- bounded exponential backoff for 408/429/5xx, honouring `Retry-After` when present;
- persisted `last_retry_count`;
- no retry on 401/403;
- max response bytes and max pages;
- cancellation via sync-job flag;
- context-manager / `close()` for internally created clients;
- redacted logs (credentials, tokens, names, narratives).

Nonnumeric analytics values are rejected and flagged (`invalid_value` / `value_invalid`). They are not converted to missing/`None`. A missing analytics row remains distinct from an invalid supplied value.

If `DHIS2_BASE_URL` and credentials are absent, connectors raise `Dhis2NotConfiguredError`. Sync jobs then fail with:

`Connector implementation complete; live DHIS2 verification pending authorised endpoint configuration and credentials.`

Error messages do not include credentials or sensitive query parameters.

`GET /ready` reports `dhis2: not_configured` or `configured_unverified`. DHIS2 unavailability does not mark the process unhealthy when the database is available.

## Adapter contract

Connectors emit:

- `AggregateObservation` — org-unit UID, period, item UID, optional COC, numeric value or null, freshness, checksum;
- `EventObservation` — event UID, connector, programme/stage, org unit, status, dates, minimised data values;
- `EventAggregateObservation` — org unit, period, metric, value.

Absence is preserved. Missing rows are not converted to zero.

Current raw-aggregate uniqueness includes source system, org unit, period, source key, and category option combination so one category row cannot supersede another.

## Live verification

Owner-supplied host text is approximately `HMIS.hhs.go.ug` via `DHIS2_BASE_URL`. The exact production URL, authentication method, and credentials remain unverified.

**Status:** Connector implementation complete; live DHIS2 verification pending authorised endpoint configuration and credentials.

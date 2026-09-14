# DHIS2 Integration Notes

## Integration boundary

DHIS2 is the authoritative routine-data source. The production base URL must be configuration-driven (expected host text: `HMIS.hhs.go.ug`), using `DHIS2_BASE_URL`; exact endpoint, authentication method, credentials, UIDs, and access scopes remain TBD. Never commit credentials or hard-code mappings.

Phase 2 adapters are implemented in `backend/app/integrations/dhis2/`. See `docs/architecture/DHIS2_CONNECTORS.md`. Live verification is pending.

## Required connector families

| Data need | DHIS2 strategy | Purpose |
|---|---|---|
| Routine aggregate HMIS | Analytics API | ANC, deliveries, CS, immunization, child-health totals and other aggregate inputs. |
| Analytical event extracts/summaries | Event Analytics query and aggregate endpoints | Filtered line-list-shaped data, trends, causes, and high-volume event summaries. |
| Current operational event state | Tracker Events API | `ACTIVE`/`COMPLETED`, UID, occurred/completed dates, data values, workflow state, and reconciliation. |

For MPDSR, Event Analytics and Tracker are complementary. If they differ due to analytics refresh latency, show freshness metadata and do not present them as identical snapshots.

## Mapping and data contracts

- Maintain an analytical geography master mapped to DHIS2 organisation units, with stable IDs, historical validity, parentage, and optional geometries.
- Keep data-element/indicator, category-option-combination, program, program-stage, event-field, and semantic mappings in administrator-managed versioned configuration.
- Raw aggregate and event snapshots retain source IDs, extraction time, source period/org unit, mapping version, and provenance for reproducible runs.
- Approved spreadsheet extracts are a fallback only; normalize them to the same raw-data contract.

## Reliability, freshness, and safety

- Use bounded retrieval, org-unit filters, pagination, cache/materialised calculations, incremental refresh, retries with exponential backoff, timeouts, job status, and monitoring.
- Do not make dashboards synchronously depend on several live DHIS2 calls. Design loading, no-data, stale-data, mapping-error, and permission-denied states.
- Refresh cadence is configurable/TBD; likely frequent recent-period and less frequent historical refresh.
- Store source freshness on values and exports. Metadata drift and mapping failure must become quality/operational signals.
- Authenticate securely and enforce application geography/programme/action permissions in addition to DHIS2 access.

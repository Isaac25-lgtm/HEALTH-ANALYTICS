# DHIS2 Integration Notes

## Integration boundary

DHIS2 is the authoritative routine-data source. The base host is known -
`https://hmis.health.go.ug` (D-049) - and stays configuration-driven through `DHIS2_BASE_URL`.
Never commit credentials or hard-code production mappings.

The configured local credential was used for authorised, bounded, read-only verification on
2026-09-20 against DHIS2 2.41.8.1. Its capture scope is Pader, but its data-view root is
`MOH - Uganda`: one non-sensitive BCG query returned all 146 district/city rows, whose sum exactly
matched the national value. This proves national read access; it did not import data or approve a
mapping. No governed production refresh has run because the national hierarchy, source mappings,
population version and boundaries remain unapplied. A dedicated read-only service identity and
rotation of the disclosed personal credential are still required before hosting.

Phase 2 adapters are implemented in `backend/app/integrations/dhis2/`. See
`docs/architecture/DHIS2_CONNECTORS.md` and `OWNER_APPROVAL_PACKET.md`.

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
- Retrieve category-specific aggregate data with an approved exact `DE.COC` operand. Never request
  every category combination and silently discard unapproved rows.
- Translate internal periods to DHIS2 ISO periods on requests and normalise every response back to
  its internal period. Non-summable mappings use complete monthly components under their approved
  semantics; missing components remain unavailable.
- Raw aggregate and event snapshots retain source IDs, extraction time, source period/org unit, mapping version, and provenance for reproducible runs.
- Approved spreadsheet extracts are a fallback only; normalize them to the same raw-data contract.

## Reliability, freshness, and safety

- Use bounded retrieval, org-unit filters, pagination, cache/materialised calculations, incremental refresh, retries with exponential backoff, timeouts, job status, and monitoring.
- National aggregate extraction requires the complete 146-unit district/city peer cohort with one
  unique effective mapping per unit. A partial national mapping is a configuration failure, never
  a successful small total.
- Do not make dashboards synchronously depend on several live DHIS2 calls. Design loading, no-data, stale-data, mapping-error, and permission-denied states.
- Scheduled refresh remains disabled pending governed mappings and production worker/Redis setup.
- Store source freshness on values and exports. Metadata drift and mapping failure must become quality/operational signals.
- Authenticate securely and enforce application geography/programme/action permissions in addition to DHIS2 access.

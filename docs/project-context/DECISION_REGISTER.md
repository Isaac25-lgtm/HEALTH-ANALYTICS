# Decision Register

| ID | Binding decision | Source / status |
|---|---|---|
| D-001 | First production release is MNCH, including ANC, intrapartum/newborn, immunization/EPI, and perinatal + maternal MPDSR. | Binding |
| D-002 | User lands at highest authorised analytical geography; geography, programme, and action permissions are enforced server-side. | Binding |
| D-003 | Geography is Uganda → region/sub-region → district/city → sub-county → facility, with future extensible groupings. | Binding |
| D-004 | FY2024/25 uses 2024 population and FY2025/26 uses 2025 population under current convention; resolution is configuration/versioned. | Binding |
| D-005 | Facility population absence does not block service-derived measures; authorised, versioned catchment-population workflow fills the gap. | Binding |
| D-006 | Aggregate numerator and denominator first; do not average child percentages by default. | Binding |
| D-007 | BLUE is a data-quality/non-assessable state, never achievement; retain actual values and quality flags. | Binding |
| D-008 | DHIS2 aggregate Analytics + Event Analytics + Tracker architecture is required; source metadata mappings are configuration. | Binding |
| D-009 | Active MPDSR events are not completed and must display as `Active (not completed)`. | Binding |
| D-010 | Perinatal notification/review target is ≥90%; maternal notification/review target is 100%. | Binding |
| D-011 | Notification timeliness may use same/next calendar day only as an explicit proxy when exact timestamp is unavailable; review timeliness is 0–7 calendar days from death date. | Binding |
| D-012 | AI never calculates indicators; external AI is not sent raw sensitive MPDSR line lists by default. | Binding |
| D-013 | Exports reuse deterministic calculation runs, respect identical permissions, and use approved templates. | Binding |
| D-014 | District-facility comparison is required, not optional. | Binding |
| D-015 | UI remains compact blue/navy DHIS2-like with an extremely subtle natural background. | Binding |
| D-016 | MV1–MV4 all use 4.3% target population coefficient. | Binding |
| D-017 | Phase 1 stack is FastAPI + Next.js/TypeScript + SQLAlchemy/Alembic + PostgreSQL, with Redis/Celery configuration only. Local JWT users are development scaffolding. | Binding (Phase 1) |
| D-018 | Phase 2 connectors are configuration-driven and verified with mocked HTTP. Live DHIS2 is not claimed until the owner supplies a verified URL, auth method, and credentials. | Binding (Phase 2) |
| D-019 | Browser authentication is cookie-only: HTTP-only session cookie, readable CSRF cookie, no access token in JSON or localStorage. | Binding (Phase 1/2 correction) |
| D-020 | Alembic historical revisions are explicit frozen schemas. Future ORM changes must not mutate 0001 or 0002. | Binding (Phase 1/2 correction) |
| D-021 | Phase 3 modules are API/service layers over the shared engines. Denominator coefficients stay in versioned configuration, not UI conditionals. | Binding (Phase 3) |
| D-022 | Phase 4 dashboards consume typed APIs. Maps use the server geometry endpoint. Owner GeoJSON is not applied until hierarchy, mappings, effective date, and `manage_mappings` are supplied. | Binding (Phase 4) |
| D-023 | AI is optional. The gateway uses a redacted evidence package and a deterministic fallback. It never calculates official values or receives identifying MPDSR line lists. | Binding (Phase 5) |
| D-024 | Publishing is code-generated from the calculation run. Official MoH templates are not invented; platform-default outputs are labelled as such. | Binding (Phase 6) |
| D-025 | Production settings reject placeholder secrets, SQLite, insecure cookies, and AI-without-key. SQLite backup is local-only; PostgreSQL uses host pg_dump. | Binding (Phase 7) |

## Material amendment — 2026-09-13

These decisions come from the owner's material amendment to the corrective prompt. Rows marked *implemented default* are fail-closed choices made where the amendment left a detail open; they need owner acceptance.

| ID | Decision | Source / status |
|---|---|---|
| D-026 | Analytical execution is a CSRF-protected POST (`/analytics/dashboard/query`, `/analytics/modules/{module}/query`) that commits calculation runs and one snapshot. GET routes never mutate. Committed snapshots are read with `GET /analysis-snapshots/{id}`, owner-only, with geography and programme re-checked on every read. A client `request_key` makes repeated submissions return the committed snapshot. | Amendment §1 |
| D-027 | Candidate population workbook identity is its SHA-256. A changed checksum is a new source that needs a new decision. NATIONAL TOTAL is not a unit. Import creates draft census (2024) and projection (2025–2030) versions after exact reconciliation; the Region column is descriptive only. | Amendment §2/§3 and owner instructions |
| D-028 | Source names map to organisation units only by exact normalised name plus type, or by an approved alias that preserves both names and was decided by a second reviewer. | Amendment §3; second-reviewer rule is an *implemented default* mirroring population approval |
| D-029 | Existing FY population rules apply to full financial years only. Months, quarters and half-years need an explicit approved rule; without one, population-derived values are unavailable (`population_rule_missing`). | Amendment §4 |
| D-030 | Facility catchment entries are facility-only. Parent populations come from a direct approved value or one complete district/city cohort of the same approved version; they are never summed from facility entries or attributed to a national version. | Amendment §5 |
| D-031 | An empty MPDSR cohort is a verified zero only with successful, complete, scoped, current Tracker coverage; otherwise the count is unknown with a reason. | Amendment §6 |
| D-032 | Numerator and denominator must share one aggregation scope and mapping version; otherwise the value is unavailable with `incompatible_aggregation_scope`, `mixed_levels` or `mixed_mapping_versions` and a quality flag. | Amendment §7 |
| D-033 | Districts and cities are aggregation peers (`district_equivalent`). A district-plus-facility mix is rejected; nested units of one class are not double-counted; a missing child makes the parent incomplete. | Amendment §8 |
| D-034 | Change and ranking are direction-aware (higher, lower, desired range). BLUE, missing and non-assessable values are excluded from rankings; unclassified (TBD) indicators and small-count mortality/MPDSR indicators are not ranked. | Amendment §9; list of unsafe indicators is an *implemented default* |
| D-035 | MPDSR cause patterns are withheld below regional level, without programme and event permission, and without an approved minimum cell count; single-reporting-unit categories are suppressed. | Amendment §10; single-unit suppression is an *implemented default* |
| D-036 | Blame, negligence and unsupported causation are refused. Provider output must be schema-valid statements (`hpip.statements.v1`) that cite evidence codes and contain no unsupported numbers; otherwise the deterministic fallback is used. | Amendment §11 |
| D-037 | Freshness is recorded after final status, finish time and duration; source freshness is the oldest reported observation; a failed attempt never overwrites the last successful timestamps. | Amendment §12 |
| D-038 | The map cohort is exactly the authorised value rows, at one administrative level, with geometry in force at the period end. Geometry from another level is never substituted. | Amendment §13 |
| D-039 | The HTML prototype is a layout and interaction reference only; its values, labels, thresholds, mappings, composite scores and client-side calculations are prohibited. No Google Fonts dependency. | Amendment §14 and owner instructions |
| D-040 | Export labels, MIME types and extensions come from one registry. Governance columns are never silently blank; PowerPoint paginates every indicator; Word/PDF stay unavailable until approved generators exist. | Amendment §15 |
| D-041 | DHIS2 remains the authoritative source. PostgreSQL is limited to the platform control and provenance plane: authorisation, approved configuration/mappings, versioned formula and population metadata, short-lived aggregate cache and analytical snapshots, export-job state, and audit records. Raw DHIS2 extracts and identifiable MPDSR material must not be retained beyond owner-approved short retention; raw MPDSR persists only minimised fields necessary for approved analytics. | Owner decision, 2026-09-13 |

See [ANALYTICAL_RULES.md](ANALYTICAL_RULES.md) for the complete formula and threshold subset retained for navigation.

## Pre-DHIS2 productionisation — owner decisions, 2026-09-14

Recorded from the owner's written execution instruction of 2026-09-14. Engineering choices made to implement them are listed separately below and are **not** owner decisions.

| ID | Binding decision | Source / status |
|---|---|---|
| D-042 | Hosting: application on Render, PostgreSQL on Neon initially. Code stays provider-neutral through `DATABASE_URL` (pooled runtime connection), an optional direct `MIGRATION_DATABASE_URL`, and TLS required in production. Render-generated URLs are acceptable for UAT; no custom domain is required. | Owner decision, 2026-09-14 |
| D-043 | Retention defaults, all configurable: routine raw aggregates 7 days; minimised MPDSR event cache 24 hours; generated export files 24 hours; export-job metadata 90 days; calculation snapshots, evidence and provenance 36 months; audit logs 24 months. | Owner decision, 2026-09-14 (completes the durations D-041 left open) |
| D-044 | Authentication for initial UAT uses local HPIP accounts. SSO and MFA may follow. No synthetic login values in production; geography, programme and action enforcement stays server-side. | Owner decision, 2026-09-14 |
| D-045 | Population periods: calendar year N uses population year N; a financial year uses its first (base) year; months, quarters and half-years inside a financial year use that financial year's base year. Population-derived annual target denominators are scaled by period fraction (12/12, 6/12, 3/12, 1/12); service-derived denominators are never scaled. National population is the sum of the 146 district/city rows. No sub-county or facility population is invented. Extends the FY-only scope of D-004. | Owner decision, 2026-09-14 |
| D-046 | `Uganda_District_City_Populations_2024_2030 (1).xlsx` is the approved district/city population source, subject to checksum verification. Verified: the repository copy `Uganda_District_City_Populations_2024_2030.xlsx` has SHA-256 `5ae43dca…3e75072`, identical to the checksum recorded at receipt. Approval of the source does not approve any organisation-unit crosswalk. | Owner decision, 2026-09-14; checksum verified 2026-09-14 |
| D-047 | Refresh: both scheduled and permission-controlled on-demand refresh are required later. Default cadence for recent/current aggregate periods is every six hours; closed historical periods are not repeatedly refreshed; continuous polling is prohibited. | Owner decision, 2026-09-14 (schedule prepared but disabled) |
| D-048 | Features allowed to remain disabled for UAT: external AI, MPDSR cause analysis, EPI RAG without approved thresholds, official Ministry templates, SSO/MFA, custom domain, and lower-level population-derived indicators without populations. | Owner decision, 2026-09-14 |
| D-049 | The known DHIS2 base host is `https://hmis.health.go.ug`. The host is known; credentials, metadata mappings, authenticated capability and live synchronisation remain unavailable and must not be claimed. | Owner decision, 2026-09-14 (supersedes the approximate host text) |

### Engineering implementation choices (not owner decisions)

- Period rules are seeded as approved `PeriodPopulationRule` rows for 2024–2030 only, the approved workbook horizon; later periods return `population_rule_missing`.
- Export bytes on Render are stored in PostgreSQL (`EXPORT_ARTIFACT_STORAGE=database`, 25 MB cap) because Render services do not share a disk.
- The browser calls a same-origin `/api` path proxied by Next.js so cookie-only authentication works across Render hostnames.
- Purge runs daily at 01:30 UTC through one purge service; the six-hourly DHIS2 refresh command exists but exits without contacting DHIS2.
- Boundary geometry cannot be activated without an explicit `effective_date_verified` confirmation.
- Undated legacy formula versions are permitted in development/test only unless `FORMULA_UNDATED_FALLBACK` is set (see OPEN_ITEMS).

### Engineering implementation choices, corrective pre-UAT pass (2026-09-15; not owner decisions)

- A production reference bootstrap (`scripts/bootstrap_reference_data.py`) creates the approved non-secret configuration after migrations; the neutral country root uses code `UG` with no DHIS2 UID. Conflicting existing rows fail closed.
- The Next.js `/api` proxy is a runtime route handler, not a build-time rewrite, so the backend address is never captured by `next build`. The Render API is a private service.
- Render secrets are declared once on `hpip-api` and copied to other services with `fromService … envVarKey`; the Blueprint group holds non-secret values only. The inert DHIS2 refresh cron is omitted from the initial topology.
- Plain `postgresql://` URLs are normalised to psycopg 3; URL `sslmode` takes precedence over `DB_SSLMODE` and a conflict is a configuration error.
- Maintenance run records and operational events are purged after 90 days (`OPERATIONAL_RECORD_RETENTION_DAYS`) pending owner confirmation.
- MPDSR causes are stored only as codes from an approved taxonomy; with none configured they are dropped. Event dates are stored as calendar dates only.
- Population `production_unresolved` counts every source unit unless `POPULATION_HIERARCHY_APPROVAL_REFERENCE` is recorded and the full cohort exists.

# Project Context

## Authority and status

This is a navigation summary, not a replacement for the canonical specification. The authoritative source is [the canonical handoff](../../ULTIMATE_IDE_HANDOFF_Uganda_Health_Performance_Intelligence_Platform.md), then the detailed Word blueprint. Current status: **PHASES 1–7 IMPLEMENTED — AWAITING OWNER AUDIT**. The owner authorised remaining phases on 2026-09-12. Live DHIS2 verification, official templates, and production hosting remain pending authorised inputs.

## Product summary

Uganda Health Performance Intelligence Platform is a national analytical layer above DHIS2, initially delivering MNCH: ANC, intrapartum/newborn, immunization/child health, and MPDSR. It is not a second data-entry system or merely a dashboard. It turns authorised source data into reproducible calculations, diagnostics, drill-down, maps, trends, evidence-safe AI explanations, and professional exports from Uganda to health-facility level.

## Current release scope

- MNCH, including ANC, intrapartum/newborn, EPI/immunization, and both perinatal and maternal MPDSR.
- Geography: Uganda → region/sub-region → district/city → sub-county → health facility.
- Mandatory screens: national overview, regional overview, district-facility comparison, facility profile, and combined MPDSR workspace.
- HIV, TB, malaria as a broader programme, nutrition, WASH, and reporting performance are future configuration-driven expansions; do not add them to initial navigation.

## Binding principles

- The landing geography is the highest organisational unit the authenticated user is authorised to analyse.
- Permissions have geography, programme, and action dimensions and are enforced server-side.
- DHIS2 aggregate Analytics, Event Analytics, and Tracker are all required. Tracker supplies current event state; Event Analytics supplies analytical event extracts/aggregates.
- Numerators and denominators aggregate before an indicator is calculated. Child percentages are not averaged by default.
- Population denominators are versioned/year-aware: FY2024/25 resolves to 2024 population and FY2025/26 to 2025 population.
- BLUE means data-quality/non-assessable status, not high performance. Values remain visible.
- Every value needs lineage to source metadata, population/indicator versions, and a calculation run.
- AI interprets a deterministic, permission-filtered evidence package; it never chooses formulae, RAG status, thresholds, or values.

## Architecture summary

`DHIS2 / approved imports → raw cache and metadata mappings → population + indicator registry → deterministic calculation and data-quality engines → versioned analytics store → permission-filtered APIs → dashboard / AI evidence gateway / Excel-PowerPoint-report publishing`.

The eventual data responsibilities include users/roles/scopes, analytical org units and mappings, geometries, population versions/values, programmes, versioned indicators/source mappings, raw aggregate/event snapshots, calculation runs/values, quality flags, saved views, export jobs, AI requests, and audit log. Background sync, caching, retries, pagination, freshness state, jobs, indexes, and observability are required: pages must not wait on several direct production DHIS2 calls.

## Data, AI, and publishing strategy

- Aggregate services use DHIS2 Analytics with administrator-managed mappings; never hard-code UIDs.
- MPDSR uses Event Analytics and Tracker retrieval with event status, cohort dates, current state, reconciliation, and chronology checks.
- Absent facility population affects only population-derived measures; authorised, versioned entry captures source, year, official/estimated state, user, history, and approval when governed.
- AI receives de-identified, approved aggregate evidence only, especially for maternal death analysis. It may explain, compare, recommend, draft, and support bounded Q&A in simple English.
- Excel, PowerPoint, and narrative reports reuse the deterministic calculation run and permission scope. PowerPoint uses approved templates rather than free-form AI layout.

See [ANALYTICAL_RULES.md](ANALYTICAL_RULES.md), [DHIS2_INTEGRATION_NOTES.md](DHIS2_INTEGRATION_NOTES.md), [UI_VISUAL_CONTRACT.md](UI_VISUAL_CONTRACT.md), and [OPEN_ITEMS.md](OPEN_ITEMS.md).

# ULTIMATE IDE HANDOFF — Uganda Health Performance Intelligence Platform

**Canonical context pack for architecture, prompt generation and implementation**

**Current focus:** Maternal, Newborn and Child Health (MNCH) first production release, designed from day one for national-to-facility scale and future multi-programme expansion.

**Prepared:** September 2026

## How the IDE must use this file

This Markdown file is intentionally large. It combines the detailed product/engineering blueprint, latest decisions from the working analysis, verified regression fixtures, interface rules, DHIS2 API strategy, AI/publishing guardrails, and source methodology snapshots. It exists so an IDE or coding agent can generate its own implementation prompts without losing the analytical rules that were agreed manually.

Before generating code or a prompt, the IDE should search this file for the relevant module and read the surrounding rules. Latest explicit decisions take precedence over older illustrative examples. Never infer missing production UIDs, national populations, facility populations, programme thresholds or clinical definitions.

### Status labels used conceptually throughout this handoff

- **BINDING** — agreed rule that should not change without an explicit later decision.
- **VERIFIED FIXTURE** — historical/analytical value suitable for regression tests, not automatically production data.
- **CONFIGURABLE** — must be represented in admin/configuration rather than hard-coded.
- **TBD INPUT** — production input still required.
- **MOCK-UP ONLY** — visual/layout example; numbers may be illustrative.
- **SENSITIVE** — requires stricter access/minimisation, especially MPDSR event data.

---

**UGANDA HEALTH PERFORMANCE INTELLIGENCE PLATFORM**

**Detailed Product, Data, Analytics, UI/UX and Implementation Blueprint**

Module 1: Maternal, Newborn and Child Health (MNCH)

**Purpose: provide the IDE with a complete implementation context before phased development begins.**

Version 1.0 - Detailed Blueprint - September 2026

This document is intentionally detailed. It is designed as a working product and engineering specification rather than a presentation. The IDE should treat formulas, denominator rules, aggregation logic, colour bands, privacy controls, screen behaviour and acceptance criteria as contractual unless a later approved specification explicitly supersedes them.

# Document Control and How to Use This Blueprint

The platform described here is a national, role-based Health Performance Intelligence Platform whose first production module is Maternal, Newborn and Child Health. It converts DHIS2 and other routine health data into deterministic indicators, scorecards, maps, trends, data-quality diagnostics, AI-assisted interpretation, and publication-ready Excel, PowerPoint and narrative reports. The same architecture is intended to support later modules such as malaria, HIV, TB, nutrition, reporting performance and other health programmes without replacing the core engine.

The IDE must not infer missing indicator formulas or silently alter the rules in this document. Where a rule is marked as configurable or unresolved, it must be represented in configuration and surfaced for administrator confirmation rather than hard-coded from assumption. The core principle is evidence before narrative: deterministic code calculates and validates the evidence; AI may interpret only the verified evidence package.

| **Item**                     | **Specification**                                                                    |
|------------------------------|--------------------------------------------------------------------------------------|
| Primary product              | Uganda Health Performance Intelligence Platform                                      |
| Initial module               | MNCH: ANC, intrapartum/newborn, immunization/child health, MPDSR                     |
| Default landing rule         | Highest organisational unit that the authenticated user is authorised to analyse     |
| Primary data source          | DHIS2 aggregate analytics plus Tracker/Event APIs for event-based programmes         |
| Primary deterministic engine | Indicator registry + calculation engine + data-quality engine                        |
| AI role                      | Interpretation, Q&A, recommendations and narrative generation from verified evidence |
| Publication outputs          | Dashboard, Excel workbook, PowerPoint presentation, narrative report                 |
| Geographic scope             | Uganda -\> region/sub-region -\> district/city -\> sub-county -\> health facility    |
| Security principle           | Least privilege; sensitive MPDSR data minimised before external AI use               |

## Reading order for the IDE

Developers should read Chapters 1-6 before creating domain models or APIs. Chapters 7-10 define the analytical behaviour and user experience. Chapters 11-13 define AI, publishing, security and operations. Chapter 14 contains regression tests and acceptance criteria. Chapter 15 converts the blueprint into the planned seven-phase, twenty-six-prompt implementation sequence. Appendices provide the detailed indicator catalogue, data contracts, glossary and screen checklists.

# 1. Product Vision, Scope and Non-Negotiable Principles

What the system is, what it is not, and what must remain true across every implementation phase.

## 1.1 Product vision

The product should feel like a national analytical layer above DHIS2 rather than a second data-entry system. DHIS2 remains the authoritative operational source for programme data. The platform adds a reusable layer for indicator definitions, year-specific denominator logic, geographic drill-down, performance colour coding, data-quality checks, trend analysis, maps, comparative analysis, AI-assisted interpretation and high-quality exports. A national analyst should be able to open Uganda, select a programme and period, inspect a national scorecard, drill into a region, then a district, sub-county and facility without changing applications or rebuilding formulas.

The first production release focuses on MNCH because the indicator algorithms, targets and presentation logic have already been worked through in detail. The architecture, however, must never assume that MNCH is the only programme. Programmes must be configuration-driven. Adding HIV, TB, malaria or another programme should largely consist of mapping DHIS2 metadata, defining indicators and thresholds, configuring views and validating outputs rather than creating a new application.

## 1.2 Core non-negotiables

- National-to-facility analytical hierarchy is native to the platform, not an afterthought.

- The user lands at the highest organisational unit within their authorised geography. A facility-only user never lands on a national screen.

- Indicator arithmetic is deterministic and versioned. An LLM never decides the numerator, denominator, multiplier or RAG classification.

- Aggregated indicators are calculated from aggregated numerators and denominators, never from the simple average of child percentages unless an indicator explicitly requires averaging.

- Population-based denominators are year-aware and period-aware. FY2024/25 uses the agreed 2024 population; FY2025/26 uses 2025 population under the current MNCH convention.

- Count columns and performance indicator columns are separate concepts. Counts are neutral; only indicators receive target colours.

- BLUE is a data-quality state, not a performance achievement. Values above logical bounds or non-assessable states remain visible and are not silently capped.

- Every displayed indicator must expose its formula, numerator, denominator, target, source, population year and calculation version.

- All exports must be reproducible from the same calculation run that produced the dashboard view.

- Sensitive maternal and perinatal line-list data must be minimised, access-controlled and excluded from third-party AI prompts unless appropriately de-identified and approved.

## 1.3 User outcomes

A successful user should not have to export raw DHIS2 data to Excel, manually calculate a denominator, colour a scorecard, create a map, write three findings and rebuild a PowerPoint every month. The platform should turn authorised routine data into an auditable performance product in minutes. A district MCH focal person should be able to see which facilities are driving a district gap; a regional analyst should see which districts drive the regional burden; and a national user should see regional inequities and drill into the underlying units without losing analytical context.

The system must also serve statisticians and analysts who need more than static dashboards. It should preserve numerator and denominator detail, allow trend exploration, show contribution analysis, expose data-quality flags, support custom indicator selection, and allow the user to ask natural-language questions against verified evidence.

# 2. Users, Roles, Permissions and Scope-Aware Landing Behaviour

Authorisation is based on geography, programme and action - not on a single role label.

## 2.1 Three-dimensional permission model

Every user should receive permissions across three independent dimensions. Geography scope defines which organisational units are visible. Programme scope defines which programme modules and indicators are visible. Action scope defines what the user can do: view, export, generate reports, edit populations, edit indicator definitions, manage users, manage mappings or administer AI providers. This avoids a common design error where a user who can see a district automatically gains administrative rights over all programmes within that district.

| **Dimension** | **Examples**                                               | **Enforcement**                                    |
|---------------|------------------------------------------------------------|----------------------------------------------------|
| Geography     | Uganda; Acholi; Pader; a specific sub-county; Pajule HC IV | Server-side org-unit filter on every API and query |
| Programme     | MNCH only; MNCH+EPI; all programmes                        | Indicator registry and API scope filter            |
| Action        | View; export; AI report; edit population; admin            | Endpoint permission + UI capability visibility     |

## 2.2 Landing-page rule

The landing page is the highest analytical organisational unit the user is authorised to access. This is more natural and more secure than always showing a national shell and hiding content. A national user lands on Uganda. A regional user lands on the assigned region/sub-region. A district user lands on that district. A sub-county user lands on the sub-county. A facility user lands directly on the facility profile. The selected geography is still visible in the header so the user understands the context immediately.

## 2.3 Drill-down and upward navigation

A user may drill downward only into descendants that fall inside the authorised geography. Upward navigation must not reveal data outside the authorised scope. A district user may navigate among sub-counties and facilities inside the district but must not see sibling districts. A national user may move freely across all configured levels. Permission checks must occur on the server for every data request; changing a URL parameter must never expand access.

## 2.4 Suggested roles

| **Role**                  | **Typical geography** | **Typical programme scope** | **Typical actions**                                                    |
|---------------------------|-----------------------|-----------------------------|------------------------------------------------------------------------|
| National analyst          | Uganda                | All or assigned programmes  | View, compare, map, export, AI reports                                 |
| Regional analyst          | One or more regions   | MNCH/EPI or broader         | View descendants, export, AI insights                                  |
| District MCH focal person | One district          | MNCH                        | View, facility comparison, export, update approved facility population |
| Facility user             | One facility          | Assigned programme          | View facility profile and data quality                                 |
| Data-quality officer      | Assigned geography    | Cross-programme             | View quality workspaces, reconciliation actions                        |
| System administrator      | Uganda                | All                         | Users, permissions, indicator versions, mappings, templates            |

## 2.5 Audit requirements

Changes to populations, indicator thresholds, DHIS2 mappings, PowerPoint templates, AI provider configuration and user permissions must be logged with user, timestamp, previous value, new value and reason where required. Calculated historical results must remain reproducible after configuration changes by storing the calculation version used at the time.

# 3. Geography, Population and Time Denominator Engine

How one calculation engine works from Uganda to individual facilities.

## 3.1 Analytical geography hierarchy

The platform maintains its own analytical geography master that can map to DHIS2 organisation units but is not constrained by the exact DHIS2 tree. The minimum supported hierarchy is Country -\> Region/Sub-region -\> District/City -\> Sub-county -\> Health Facility. The model should allow additional intermediate or programme-specific groupings, for example referral catchments, implementing-partner areas or historical regions, without breaking the main hierarchy.

| **Field**             | **Purpose**                                           |
|-----------------------|-------------------------------------------------------|
| org_unit_id           | Internal stable identifier                            |
| dhis2_uid             | DHIS2 organisation-unit mapping when available        |
| name                  | Canonical display name                                |
| level_type            | Country, region, district, city, sub-county, facility |
| parent_id             | Parent in analytical hierarchy                        |
| valid_from / valid_to | Supports boundary changes over time                   |
| geometry_id           | Optional polygon/point reference                      |
| active                | Controls current navigation                           |

## 3.2 Population master

Population must be stored by organisational unit and year, with source and version. The same geography may have multiple candidate estimates, but one approved population version must be selected for a calculation run. National, region, district, city and sub-county populations will be preloaded from the user-provided national population files. Facility catchment population may be imported in bulk or entered manually when absent.

Facility population entry is not a one-time uncontrolled text field. The system must capture value, reference year, source, whether it is estimated or official, the user who entered it, and approval status if governance requires approval. The value should then become available to population-based facility indicators until replaced by a later version.

## 3.3 Financial-year population rule

For the current MNCH analytical convention, FY2024/25 uses 2024 Census population and FY2025/26 uses 2025 projected population. This rule should be represented as configuration, not hidden in code, because future Ministry guidance may change how financial-year denominator populations are selected. The calculation run should store the population year resolved for every geography.

## 3.4 Period adjustment

Indicators whose denominator represents an annual target population require period adjustment when the selected analysis period is shorter than twelve months. For a quarter, the annual target is multiplied by 3/12; for a month, 1/12; for six months, 6/12. The engine should calculate the number of months represented by the selected period and apply the fraction once. It must not apply period adjustment to service-derived denominators such as ANC1, deliveries or live births.

General formula: Period target = Population(year) x target-population coefficient x months_in_period / 12. Coverage = numerator / period target x multiplier. The exact coefficient and multiplier are defined per indicator in the indicator registry.

# 4. DHIS2 Integration and Data Ingestion Architecture

Aggregate analytics for routine indicators; Event Analytics and Tracker for line-list/event programmes.

## 4.1 Integration principle

DHIS2 should remain the principal routine data source. The platform should not ask users to manually upload spreadsheets when the same authorised data are available through DHIS2. Spreadsheet import remains a controlled fallback for offline work, historical data or approved extracts. All imported sources should ultimately conform to the same internal raw-data contracts so the indicator engine does not care whether a value came from DHIS2 or an uploaded file.

## 4.2 Aggregate analytics connector

Routine aggregate data such as ANC attendance, deliveries, immunisation doses and other monthly HMIS totals should be retrieved through the DHIS2 Analytics API. The connector must support organisation-unit descendants, periods, data elements/indicators, metadata mapping, pagination where applicable, retries, caching and extraction timestamps. The connector should not embed UIDs in business logic; UIDs belong in the mapping administration layer.

## 4.3 Event Analytics query endpoint

For event programmes, DHIS2 Event Analytics can return individual event rows rather than only aggregate counts. The architecture should support /api/analytics/events/query/{program-id} for analytical event extracts and /api/analytics/events/aggregate/{program-id} for efficient aggregated summaries. Requested program-stage data elements and attributes can be returned as columns, allowing the platform to reconstruct line-list-style analytical datasets when permissions permit.

## 4.4 Tracker Events API

The Tracker Events API is required for current operational state and detailed event objects, particularly where the system needs event status, occurredAt, completedAt, created/updated metadata or current dataValues. This is especially important for MPDSR where an event may still be ACTIVE and must not be counted as a completed notification or review. Tracker should therefore complement Event Analytics rather than be replaced by it.

## 4.5 Hybrid MPDSR retrieval strategy

Use Event Analytics for high-volume analytical summaries, trends, cause distributions and filtered event tables that tolerate analytics-table refresh latency. Use Tracker Events for current ACTIVE/COMPLETED workflow state, event-level validation and operational reconciliation. When results disagree because analytics tables have not refreshed, the user interface should expose the data freshness time and avoid pretending that both sources are identical snapshots.

## 4.6 Metadata mapping

Each indicator source should be mapped through administrator-managed metadata. For an aggregate indicator this includes data-element or indicator UID, category option combination if relevant, aggregation behaviour and programme/period constraints. For event indicators it includes program UID, program-stage UID, data-element UIDs and the internal semantic field each UID represents, for example date_of_death, death_type, probable_cause_birth_asphyxia or delay_seeking_care.

## 4.7 Reliability and caching

National queries can be large. The system should cache raw DHIS2 responses and materialised calculated results by source version, period, geography and indicator set. Background sync jobs should refresh recent periods more frequently than historical periods. A user opening the dashboard should usually read from the platform database/cache rather than wait for multiple upstream calls. Every view should display the extraction or refresh time so the analytical snapshot is transparent.

## 4.8 Connector failure behaviour

If DHIS2 is unavailable, the platform should continue to serve the most recent validated cached run and clearly mark its age. It should not substitute zeros for missing upstream responses. Scheduled jobs should use exponential backoff and alert administrators after repeated failures. Authentication secrets must be stored in a secrets manager or protected environment variables, never in source code or front-end configuration.

# 5. Core Data Model, Indicator Registry and Calculation Engine

The platform is configuration-driven: formulas, thresholds and mappings live in explicit versioned structures.

## 5.1 Indicator registry

Every indicator is a first-class configuration object. At minimum it contains canonical name, code, programme, numerator specification, denominator type, coefficient or reference indicator, multiplier, unit, precision, direction, target, RAG/BLUE rules, aggregation rule, period-adjustment behaviour, valid-from period, methodology text, DHIS2 mappings and data-quality rules. The engine reads this object; it does not contain a separate handwritten function for every indicator unless a genuinely exceptional calculation requires one.

| **Property**                | **Example: ANC1 Coverage**               | **Example: PMR**                         |
|-----------------------------|------------------------------------------|------------------------------------------|
| Programme                   | MNCH - ANC                               | MNCH - Intrapartum                       |
| Numerator                   | ANC1 count                               | Fresh SB + Macerated SB + Newborn deaths |
| Denominator                 | Population-derived 5%                    | Total deliveries                         |
| Multiplier                  | 100                                      | 1,000                                    |
| Unit                        | %                                        | per 1,000 deliveries                     |
| Direction                   | Higher is better                         | Lower is better                          |
| Aggregation                 | Sum numerator / sum expected pregnancies | Sum deaths / sum deliveries              |
| Period-adjusted denominator | Yes                                      | No                                       |

## 5.2 Denominator types

The calculation engine must support population-derived denominators, service-derived denominators, event-derived denominators, composite denominators and direct percentages supplied by the source. Population-derived examples include ANC1 and immunisation coverage. Service-derived examples include first-trimester ANC / ANC1. Event-derived examples include completed MPDSR reviews / reported deaths. Direct percentages include KMC where the supplied source already provides a percentage and no appropriate raw numerator/denominator pair is available in the agreed dataset.

## 5.3 Aggregation rule

When moving from facility to sub-county, district, region or national level, the default rule is to aggregate the numerator and denominator first and then calculate the indicator. The platform must not average facility percentages. This prevents small facilities from receiving the same mathematical weight as large facilities. Direct percentages without recoverable numerator/denominator require an explicitly configured aggregation method and should be flagged in methodology because they cannot be safely rolled up by simple arithmetic unless the source supplies the aggregate percentage.

## 5.4 Performance direction and colour

The threshold engine must support higher-is-better indicators, lower-is-better indicators, desired-range indicators and inverse risk indicators. For desired-range indicators such as C-section rate, both very low and very high values can be poor. BLUE is reserved for non-performance states such as \>100% bounded percentages, N/A or clear reconciliation problems. The UI should never use GREEN merely because a value is numerically high.

## 5.5 Precision and display

Calculations should use full precision internally and round only for display. Unless otherwise stated, percentages display to one decimal place in analytical tables and may be rounded to whole numbers in compact KPI cards when visual density requires it. Rates such as PMR and MMR display with one decimal where useful. Exported calculation sheets should include the unrounded value in a hidden or explicit calculation column if reproducibility requires it.

## 5.6 Evidence package

Every calculated indicator should be able to emit an evidence package for AI and reporting. This package includes geography, period, indicator version, numerator, denominator, value, target, status, prior-period value, absolute/percentage-point change, child-unit distribution, data-quality flags, source refresh time and method text. AI receives the evidence package rather than raw uncontrolled source data whenever possible.

# 6. Detailed MNCH Indicator Catalogue and Formula Specification

Authoritative rules currently agreed for ANC, intrapartum/newborn, immunization/child health and MPDSR.

## 6.1 Antenatal care indicators

### 6.1.1 ANC1 Coverage

| **Component**                   | **Specification**                                                                                                                     |
|---------------------------------|---------------------------------------------------------------------------------------------------------------------------------------|
| Numerator                       | ANC1                                                                                                                                  |
| Denominator                     | Population x 5%                                                                                                                       |
| Multiplier                      | 100                                                                                                                                   |
| Direction                       | Higher is better                                                                                                                      |
| Performance bands               | Green \>=95%; Yellow 75.0-94.9%; Red \<75%                                                                                            |
| Implementation / interpretation | Population-derived. FY uses agreed year population. Values \>100% remain visible; review denominator/reporting before interpretation. |

The platform should calculate ANC1 Coverage at the currently selected organisational level by aggregating the required numerator and denominator across all authorised descendant units for that geography and period. It should expose both components in the methodology drawer and Excel calculation sheet. Trend calculations use the same formula for each period, with the population denominator adjusted to the selected period length only when the denominator is population-derived.

### 6.1.2 ANC1 in First Trimester

| **Component**                   | **Specification**                                                      |
|---------------------------------|------------------------------------------------------------------------|
| Numerator                       | ANC1 in first trimester                                                |
| Denominator                     | ANC1                                                                   |
| Multiplier                      | 100                                                                    |
| Direction                       | Higher is better                                                       |
| Performance bands               | Green \>=45%; Yellow 30.0-44.9%; Red \<30%                             |
| Implementation / interpretation | Service-derived denominator; no population required at facility level. |

The platform should calculate ANC1 in First Trimester at the currently selected organisational level by aggregating the required numerator and denominator across all authorised descendant units for that geography and period. It should expose both components in the methodology drawer and Excel calculation sheet. Trend calculations use the same formula for each period, with the population denominator adjusted to the selected period length only when the denominator is population-derived.

### 6.1.3 ANC4 Coverage

| **Component**                   | **Specification**                          |
|---------------------------------|--------------------------------------------|
| Numerator                       | ANC4                                       |
| Denominator                     | Population x 5%                            |
| Multiplier                      | 100                                        |
| Direction                       | Higher is better                           |
| Performance bands               | Green \>=75%; Yellow 50.0-74.9%; Red \<50% |
| Implementation / interpretation | Population-derived.                        |

The platform should calculate ANC4 Coverage at the currently selected organisational level by aggregating the required numerator and denominator across all authorised descendant units for that geography and period. It should expose both components in the methodology drawer and Excel calculation sheet. Trend calculations use the same formula for each period, with the population denominator adjusted to the selected period length only when the denominator is population-derived.

### 6.1.4 ANC8 Coverage

| **Component**                   | **Specification**                                                                |
|---------------------------------|----------------------------------------------------------------------------------|
| Numerator                       | ANC8                                                                             |
| Denominator                     | Population x 5%                                                                  |
| Multiplier                      | 100                                                                              |
| Direction                       | Higher is better                                                                 |
| Performance bands               | Green \>=15%; Yellow 7.0-14.9%; Red \<7%                                         |
| Implementation / interpretation | Population-derived; useful continuum indicator when compared with ANC1 and ANC4. |

The platform should calculate ANC8 Coverage at the currently selected organisational level by aggregating the required numerator and denominator across all authorised descendant units for that geography and period. It should expose both components in the methodology drawer and Excel calculation sheet. Trend calculations use the same formula for each period, with the population denominator adjusted to the selected period length only when the denominator is population-derived.

### 6.1.5 IPT3 Coverage

| **Component**                   | **Specification**                          |
|---------------------------------|--------------------------------------------|
| Numerator                       | IPT3                                       |
| Denominator                     | Population x 5%                            |
| Multiplier                      | 100                                        |
| Direction                       | Higher is better                           |
| Performance bands               | Green \>=75%; Yellow 50.0-74.9%; Red \<50% |
| Implementation / interpretation | Population-derived.                        |

The platform should calculate IPT3 Coverage at the currently selected organisational level by aggregating the required numerator and denominator across all authorised descendant units for that geography and period. It should expose both components in the methodology drawer and Excel calculation sheet. Trend calculations use the same formula for each period, with the population denominator adjusted to the selected period length only when the denominator is population-derived.

### 6.1.6 Hb Testing at ANC1

| **Component**                   | **Specification**                          |
|---------------------------------|--------------------------------------------|
| Numerator                       | Hb tested                                  |
| Denominator                     | ANC1                                       |
| Multiplier                      | 100                                        |
| Direction                       | Higher is better                           |
| Performance bands               | Green \>=75%; Yellow 50.0-74.9%; Red \<50% |
| Implementation / interpretation | Service-derived; denominator ANC1.         |

The platform should calculate Hb Testing at ANC1 at the currently selected organisational level by aggregating the required numerator and denominator across all authorised descendant units for that geography and period. It should expose both components in the methodology drawer and Excel calculation sheet. Trend calculations use the same formula for each period, with the population denominator adjusted to the selected period length only when the denominator is population-derived.

### 6.1.7 Iron/Folic Acid at ANC1

| **Component**                   | **Specification**                                                                                             |
|---------------------------------|---------------------------------------------------------------------------------------------------------------|
| Numerator                       | Women receiving \>=30 IFA tablets                                                                             |
| Denominator                     | ANC1                                                                                                          |
| Multiplier                      | 100                                                                                                           |
| Direction                       | Higher is better                                                                                              |
| Performance bands               | Green \>=95%; Yellow 75.0-94.9%; Red \<75%                                                                    |
| Implementation / interpretation | Do not cap \>100%. When numerator exceeds ANC1, retain the calculation and raise a definition/reporting flag. |

The platform should calculate Iron/Folic Acid at ANC1 at the currently selected organisational level by aggregating the required numerator and denominator across all authorised descendant units for that geography and period. It should expose both components in the methodology drawer and Excel calculation sheet. Trend calculations use the same formula for each period, with the population denominator adjusted to the selected period length only when the denominator is population-derived.

### 6.1.8 Obstetric Ultrasound

| **Component**                   | **Specification**                          |
|---------------------------------|--------------------------------------------|
| Numerator                       | Women receiving obstetric ultrasound       |
| Denominator                     | ANC1                                       |
| Multiplier                      | 100                                        |
| Direction                       | Higher is better                           |
| Performance bands               | Green \>=75%; Yellow 50.0-74.9%; Red \<50% |
| Implementation / interpretation | Denominator ANC1.                          |

The platform should calculate Obstetric Ultrasound at the currently selected organisational level by aggregating the required numerator and denominator across all authorised descendant units for that geography and period. It should expose both components in the methodology drawer and Excel calculation sheet. Trend calculations use the same formula for each period, with the population denominator adjusted to the selected period length only when the denominator is population-derived.

### 6.1.9 Teenage Pregnancy Among ANC1 Attendees

| **Component**                   | **Specification**                                       |
|---------------------------------|---------------------------------------------------------|
| Numerator                       | ANC1 age \<15 + ANC1 age 15-19                          |
| Denominator                     | ANC1                                                    |
| Multiplier                      | 100                                                     |
| Direction                       | Lower is better                                         |
| Performance bands               | Green \<5%; Yellow 5.0-12.9%; Red \>=13%                |
| Implementation / interpretation | Inverse indicator; do not apply higher-is-better logic. |

The platform should calculate Teenage Pregnancy Among ANC1 Attendees at the currently selected organisational level by aggregating the required numerator and denominator across all authorised descendant units for that geography and period. It should expose both components in the methodology drawer and Excel calculation sheet. Trend calculations use the same formula for each period, with the population denominator adjusted to the selected period length only when the denominator is population-derived.

## 6.2 Intrapartum and newborn indicators

### 6.2.1 Institutional Delivery Coverage

| **Component**                   | **Specification**                                                                                                            |
|---------------------------------|------------------------------------------------------------------------------------------------------------------------------|
| Numerator                       | Total deliveries                                                                                                             |
| Denominator                     | Population x 4.85%                                                                                                           |
| Multiplier                      | 100                                                                                                                          |
| Direction                       | Higher is better                                                                                                             |
| Performance bands               | Green \>=65%; Yellow 50.0-64.9%; Red \<50%                                                                                   |
| Implementation / interpretation | Coverage may exceed 100% because expected deliveries are estimated. Do not cap and do not automatically mark \>100% as blue. |

Institutional Delivery Coverage should use the same formula at national, regional, district, sub-county and facility level whenever the required source fields are available. At higher levels, the engine aggregates counts before calculating the rate or percentage. The UI must preserve the unit in every table, tooltip and export so a rate per 1,000 or per 100,000 is never rendered with a percent sign.

### 6.2.2 Caesarean Section Rate

| **Component**                   | **Specification**                                                     |
|---------------------------------|-----------------------------------------------------------------------|
| Numerator                       | Caesarean sections                                                    |
| Denominator                     | Total deliveries                                                      |
| Multiplier                      | 100                                                                   |
| Direction                       | Desired range                                                         |
| Performance bands               | Green 5.0-15.0%; Yellow 3.0-4.9% or 15.1-20.0%; Red \<3.0% or \>20.0% |
| Implementation / interpretation | Range indicator; higher is not always better.                         |

Caesarean Section Rate should use the same formula at national, regional, district, sub-county and facility level whenever the required source fields are available. At higher levels, the engine aggregates counts before calculating the rate or percentage. The UI must preserve the unit in every table, tooltip and export so a rate per 1,000 or per 100,000 is never rendered with a percent sign.

### 6.2.3 LBW Babies Initiated on KMC

| **Component**                   | **Specification**                                                                         |
|---------------------------------|-------------------------------------------------------------------------------------------|
| Numerator                       | Source KMC percentage                                                                     |
| Denominator                     | Direct percentage                                                                         |
| Multiplier                      | 1                                                                                         |
| Direction                       | Higher is better                                                                          |
| Performance bands               | Green 95.0-100.0%; Yellow 75.0-94.9%; Red \<75%; Blue \>100%                              |
| Implementation / interpretation | Use source percentage directly under current data contract. \>100% is data-quality state. |

LBW Babies Initiated on KMC should use the same formula at national, regional, district, sub-county and facility level whenever the required source fields are available. At higher levels, the engine aggregates counts before calculating the rate or percentage. The UI must preserve the unit in every table, tooltip and export so a rate per 1,000 or per 100,000 is never rendered with a percent sign.

### 6.2.4 Successful Resuscitation

| **Component**                   | **Specification**                                                                 |
|---------------------------------|-----------------------------------------------------------------------------------|
| Numerator                       | Successfully resuscitated                                                         |
| Denominator                     | Birth asphyxia cases                                                              |
| Multiplier                      | 100                                                                               |
| Direction                       | Higher is better                                                                  |
| Performance bands               | Green 90.0-100.0%; Yellow 70.0-89.9%; Red \<70%; Blue \>100%                      |
| Implementation / interpretation | A result \>100% is logically impossible under the agreed denominator and is BLUE. |

Successful Resuscitation should use the same formula at national, regional, district, sub-county and facility level whenever the required source fields are available. At higher levels, the engine aggregates counts before calculating the rate or percentage. The UI must preserve the unit in every table, tooltip and export so a rate per 1,000 or per 100,000 is never rendered with a percent sign.

### 6.2.5 Perinatal Mortality Rate

| **Component**                   | **Specification**                        |
|---------------------------------|------------------------------------------|
| Numerator                       | Fresh SB + Macerated SB + Newborn deaths |
| Denominator                     | Total deliveries                         |
| Multiplier                      | 1000                                     |
| Direction                       | Lower is better                          |
| Performance bands               | Green \<=12; Yellow \>12-20; Red \>20    |
| Implementation / interpretation | Display as rate per 1,000, never as %.   |

Perinatal Mortality Rate should use the same formula at national, regional, district, sub-county and facility level whenever the required source fields are available. At higher levels, the engine aggregates counts before calculating the rate or percentage. The UI must preserve the unit in every table, tooltip and export so a rate per 1,000 or per 100,000 is never rendered with a percent sign.

### 6.2.6 Fresh Stillbirth Rate

| **Component**                   | **Specification**                                         |
|---------------------------------|-----------------------------------------------------------|
| Numerator                       | Fresh stillbirths                                         |
| Denominator                     | Total deliveries                                          |
| Multiplier                      | 1000                                                      |
| Direction                       | Lower is better                                           |
| Performance bands               | Green \<=5; Yellow \>5-10; Red \>10                       |
| Implementation / interpretation | Quality signal; do not infer causation from routine data. |

Fresh Stillbirth Rate should use the same formula at national, regional, district, sub-county and facility level whenever the required source fields are available. At higher levels, the engine aggregates counts before calculating the rate or percentage. The UI must preserve the unit in every table, tooltip and export so a rate per 1,000 or per 100,000 is never rendered with a percent sign.

### 6.2.7 Maternal Mortality Ratio

| **Component**                   | **Specification**                                             |
|---------------------------------|---------------------------------------------------------------|
| Numerator                       | Maternal deaths                                               |
| Denominator                     | Live births                                                   |
| Multiplier                      | 100000                                                        |
| Direction                       | Lower is better                                               |
| Performance bands               | Green \<=183; Yellow 184-300; Red \>300                       |
| Implementation / interpretation | Use live births denominator; display per 100,000 live births. |

Maternal Mortality Ratio should use the same formula at national, regional, district, sub-county and facility level whenever the required source fields are available. At higher levels, the engine aggregates counts before calculating the rate or percentage. The UI must preserve the unit in every table, tooltip and export so a rate per 1,000 or per 100,000 is never rendered with a percent sign.

## 6.3 Immunization and child-health target-population coefficients

| **Service / target group**         | **Annual target coefficient** |
|------------------------------------|-------------------------------|
| BCG                                | 4.85%                         |
| OPV0                               | 4.85%                         |
| Hepatitis B birth dose             | 4.85%                         |
| OPV1                               | 4.3%                          |
| DPT-HepB-Hib1                      | 4.3%                          |
| RotaV1                             | 4.3%                          |
| PCV1                               | 4.3%                          |
| IPV1                               | 4.3%                          |
| OPV2                               | 4.3%                          |
| DPT-HepB-Hib2                      | 4.3%                          |
| PCV2                               | 4.3%                          |
| RotaV2                             | 4.3%                          |
| OPV3                               | 4.3%                          |
| DPT-HepB-Hib3                      | 4.3%                          |
| IPV2                               | 4.3%                          |
| PCV3                               | 4.3%                          |
| Malaria Vaccine Dose 1             | 4.3%                          |
| Malaria Vaccine Dose 2             | 4.3%                          |
| Malaria Vaccine Dose 3             | 4.3%                          |
| Malaria Vaccine Dose 4             | 4.3%                          |
| Measles-Rubella                    | 4.3%                          |
| Yellow Fever                       | 4.3%                          |
| Td women 15-49                     | 23%                           |
| HPV girls                          | 1.53%                         |
| Vitamin A 6-11 months              | 1.93%                         |
| Vitamin A / Deworming 12-59 months | 16.2%                         |
| Deworming 1-14 years               | 49.3%                         |
| Under-5 target                     | 20.5%                         |

For full-financial-year coverage, denominator = annual population x coefficient. For a quarter, multiply by 3/12; for a month, multiply by 1/12. Malaria Vaccine Dose 4 is explicitly configured at 4.3%, the same annual target coefficient as doses 1-3. These coefficients belong in a versioned denominator table rather than scattered throughout application code.

Coverage RAG thresholds for immunisation indicators should be configurable from approved programme guidance. Where an authoritative threshold has not yet been supplied in the project context, the platform must not invent one. The indicator can still calculate and display its value while administrators configure the approved target and bands.

## 6.4 Immunization dropout and continuum analytics

The immunisation module should support dropout indicators such as Penta1-to-Penta3 and MV1-to-MV4. General formula: dropout = (Dose1 - FinalDose) / Dose1 x 100. Dropout is an inverse indicator, so lower values are better, but the exact programme thresholds should be configurable. A continuum visual should display entry, intermediate and completion doses to distinguish weak access from weak completion.

## 6.5 MPDSR perinatal process indicators

| **Indicator**                       | **Formula / definition**                                         | **Target**    | **Colour rule**                                                     |
|-------------------------------------|------------------------------------------------------------------|---------------|---------------------------------------------------------------------|
| Perinatal deaths reported           | Fresh SB + Macerated SB + Newborn deaths                         | Count         | Neutral count                                                       |
| Perinatal deaths notified           | COMPLETED notification events in death cohort                    | Count         | Neutral count                                                       |
| % perinatal deaths notified         | Completed notifications / reported deaths x100                   | \>=90% target | Green \>=90%; Yellow 75-89.9%; Red \<75%; Blue \>100/reconciliation |
| % perinatal deaths notified on time | Same/next calendar-day notification proxy / reported deaths x100 | \>=90% target | Green \>=90%; Yellow 75-89.9%; Red \<75%                            |
| Perinatal deaths reviewed           | COMPLETED review events in death cohort                          | Count         | Neutral count                                                       |
| % perinatal deaths reviewed         | Completed reviews / reported deaths x100                         | \>=90% target | Green \>=90%; Yellow 75-89.9%; Red \<75%; Blue \>100/reconciliation |
| % perinatal deaths reviewed on time | Completed reviews within 0-7 days / reported deaths x100         | \>=90% target | Green \>=90%; Yellow 75-89.9%; Red \<75%                            |

The perinatal death cohort should be defined by date of death within the selected reporting period. Event status must be COMPLETED for a record to count as a completed notification or review. ACTIVE events are shown separately as not completed. For exact notification timeliness, the source would need a timestamp; when only a notification date is available, same day or next calendar day is used as the operational proxy and the methodology note must say so.

## 6.6 MPDSR maternal process indicators

| **Indicator**                      | **Formula / definition**                                      | **Target**  | **Colour rule**                                  |
|------------------------------------|---------------------------------------------------------------|-------------|--------------------------------------------------|
| Maternal deaths reported           | Aggregate reported maternal deaths                            | Count       | Neutral count                                    |
| Maternal deaths notified           | Completed maternal notification events                        | Count       | Neutral count                                    |
| % maternal deaths notified         | Completed notifications / reported deaths x100                | 100% target | Green 100%; Yellow 90-99.9%; Red \<90%           |
| % maternal deaths notified on time | Verifiable same/next-day notifications / reported deaths x100 | 100% target | Green 100%; Yellow 90-99.9%; Red \<90%; Blue N/A |
| Maternal deaths reviewed           | Completed maternal review events                              | Count       | Neutral count                                    |
| % maternal deaths reviewed         | Completed reviews / reported deaths x100                      | 100% target | Green 100%; Yellow 90-99.9%; Red \<90%           |
| % maternal deaths reviewed on time | Completed reviews within 0-7 days / reported deaths x100      | 100% target | Green 100%; Yellow 90-99.9%; Red \<90%           |

Maternal death analysis is more sensitive than ordinary aggregate performance. District-level process counts and percentages are acceptable when permissions allow, but clinical cause analysis should default to regional or national aggregation, especially when district denominators are very small. The system must avoid exposing exact date + facility + rare cause combinations that could identify an individual case.

# 7. Module-Level Analytical Behaviour

What each MNCH module should calculate beyond the basic scorecard.

## 7.1 ANC module

The ANC module must support coverage, quality and risk indicators in one coherent continuum. The principal analytical views are current-period scorecard, year-on-year comparison, monthly trend, ANC1-\>ANC4-\>ANC8 continuum, district/facility ranking, contribution to regional gap, map view and data-quality warnings. The module should be able to answer whether a low ANC4 value is primarily due to low ANC1 access or poor continuation after first contact by showing both the absolute coverage denominator and the ANC1-to-ANC4 retention relationship.

At facility level, the module should request catchment population only when a population-derived indicator is selected and no approved facility population exists. Service-derived indicators such as first-trimester proportion and Hb testing can calculate without population. The UI should not block the entire facility profile because one denominator is missing; it should mark only affected indicators as requiring population.

## 7.2 Intrapartum/newborn module

The intrapartum module should combine access indicators, intervention range indicators and outcome indicators while respecting different directions. Institutional delivery can legitimately exceed 100% because expected deliveries are estimated and referral facilities may serve people outside the denominator. C-section is a desired-range indicator. PMR, fresh stillbirth rate and MMR are inverse outcome indicators. This difference should be obvious in tooltips and scorecard legends so users do not interpret every green cell as high numerical performance.

Year-on-year analysis should show current value, previous value, absolute change, status transition and underlying event counts. Mortality ratios with small district counts should always show the death count alongside the rate. AI commentary should explicitly avoid causal claims such as “poor care caused the deaths” unless a formal adjudicated source supports the statement.

## 7.3 Immunization and child-health module

The EPI module should show antigen coverage, dropout, completion, timeliness where available, zero/low-performing facilities, monthly/quarterly target progress and maps. Birth-dose antigens use 4.85% annual population while the infant series and malaria vaccine doses 1-4 use 4.3%. The engine must scale target denominators by period. A facility scorecard should allow users to distinguish a denominator problem, a reporting gap and a genuine coverage gap.

Useful visuals include vaccine continuum bars, dose-to-dose dropout, monthly administered doses against monthly expected target, district/facility RAG maps and ranking of facilities with the largest number of missed target children. If numerators exceed plausible target populations, the platform should retain the value but flag potential catchment, denominator or reporting issues.

## 7.4 MPDSR module

MPDSR should combine aggregate reported deaths with event-level notification and review records. The first screen is a combined perinatal and maternal process scorecard showing reported, notified, reviewed and timeliness indicators. Deep-dive views should then analyse process performance by quarter, active/not-completed events, reconciliation gaps, impossible date sequences, cause documentation and cause distributions. Maternal clinical findings should be aggregated more conservatively than perinatal findings.

A true case-level cascade is only valid if a shared unique case/event identifier exists across reported, notification and review stages. Without it, the platform may compare aggregate counts but must not claim that a specific notified case is the same specific reviewed case. The system should recommend a common MPDSR identifier and support it when available.

# 8. Data Quality, Reconciliation and Statistical Analytics

The platform should identify why a number may be wrong, not merely paint it red.

## 8.1 Data-quality engine

Data quality is a separate analytical dimension from programme performance. A poor performance value may be real, while a high value may be invalid. The platform should therefore produce explicit quality flags with severity, rule, affected indicator/event, geography, period, evidence and recommended follow-up. BLUE should be used in scorecards for data-quality states where the value cannot be interpreted as normal performance.

| **Rule**                        | **Detection concept**                                                         | **Expected behaviour**                                         |
|---------------------------------|-------------------------------------------------------------------------------|----------------------------------------------------------------|
| Bounded percentage \>100%       | Numerator exceeds logical denominator for a bounded proportion                | Blue; retain value; request reconciliation                     |
| Aggregate vs line-list mismatch | Completed line-list count differs from reported aggregate count               | Flag net difference; never cap percentage                      |
| Impossible chronology           | Notification/review date precedes recorded death date                         | Exclude from timely numerator; flag date correction            |
| ACTIVE event                    | Event not completed                                                           | Show as active/not completed; exclude from completed numerator |
| Missing denominator             | Population/service denominator unavailable or zero                            | Do not calculate; show N/A with reason                         |
| Unexpected zero                 | Zero follows sustained non-zero series or appears across high-volume facility | Flag for review, not automatic error                           |
| Late/stale reporting            | Latest reporting period missing or updated after deadline                     | Show recency/late reporting warning                            |
| Cause documentation missing     | No structured probable cause populated in completed review                    | Quality flag and facility follow-up                            |
| Duplicate/near duplicate        | Same event signature, facility, date, type or identifier duplicated           | Require reconciliation before removal                          |

## 8.2 Trend engine

The trend engine should support monthly, quarterly, financial-year and rolling-period series. It should use raw counts for event burden when monthly denominators are not available and should not fabricate rates by dividing monthly deaths by annual denominators. For coverage indicators, period-specific denominators are calculated correctly for each month/quarter. Users should be able to toggle current year, prior year, multi-year trend and selected organisational units.

## 8.3 Comparison engine

Comparison should calculate current value, previous value, percentage-point change for percentages, absolute rate change for rates, direction of improvement, and colour transition. It must understand inverse indicators so a decline in PMR is improvement while a decline in ANC4 is deterioration. The engine should provide child-unit contribution to the change when possible.

## 8.4 Contribution and Pareto analysis

Contribution analysis should answer which child units drive a regional or national burden or gap. For counts, contribution is child count / parent count. For target gaps, contribution can be based on missed target quantity rather than percentage ranking. Pareto analysis can identify the smallest set of districts/facilities responsible for a large share of the regional shortfall. The system should label these as descriptive contributions rather than risk ratios.

## 8.5 Anomaly detection

Anomaly detection should initially use transparent statistical rules rather than opaque machine-learning models. Candidate methods include rolling median/MAD, z-score against seasonal baseline, percentage-change thresholds, unexpected zeros and run rules for sustained deterioration. Every alert must show why it fired and the reference period. Later, more advanced forecasting models may be added without changing the evidence contract.

## 8.6 “Why is this red?” drill-down

Every red or blue scorecard cell should be explainable without AI. The drill-down should show numerator, denominator, target, formula, prior value, trend, child-unit distribution, data-quality flags and top contributors to the gap. AI may then summarise these facts in plain language. This design prevents the system from becoming an opaque dashboard where users can see a colour but cannot understand the underlying evidence.

# 9. Dashboard UX, Navigation and Screen Specifications

Restore the approved DHIS2-like blue format, keep the background natural only in a subtle supporting role.

## 9.1 Visual design contract

The approved visual direction is a clean DHIS2-like blue/navy interface with white analytical cards, strong information hierarchy, compact scorecards and restrained RAG colours. The natural aesthetic should be subtle: faint blue gradients, soft organic background shapes or very low-contrast botanical texture in unused areas. It must never compete with the data. The previous green-heavy redesign is not the baseline. The original blue layout is the baseline, with only subtle natural refinement.

Tables, cards and charts remain crisp and predominantly white. The left navigation is dark navy/blue with the Ministry branding. Typography is modern and readable. The system should feel polished and calm rather than decorative. Avoid giant hero banners, scenic landscapes, excessive rounded marketing cards, gradients inside charts, 3D effects or illustrations that change the analytical layout.

**Visual reference 1 - National performance overview.** Preserve the original blue/navy DHIS2-like format: top scope/period/compare controls, KPI cards, regional map, AI insights, regional scorecard, monthly trends and downloads. The image is a layout reference; its displayed values are mock-up values unless separately listed as verified fixtures.

**Visual reference 2 - Regional/sub-regional overview.** Preserve district map, priority insights, district scorecard, trends and priority district analysis in the same blue/navy visual system.

**Visual reference 3 - Facility performance profile.** Preserve facility metadata, catchment-population workflow, KPI strip, monthly trends, indicator scorecard, data-quality alerts, AI summary/recommendations and downloads.

**Visual reference 4 - MPDSR screen.** Preserve combined perinatal/maternal process scorecard, cause-pattern panels, quarterly process performance, data-quality issues, key learning and downloads.

**Visual reference 5 - District-specific facility comparison.** Preserve the facility comparison table, district insights, facility trend chart, top/bottom facility analysis, scope controls and downloads.

## 9.2 National overview

Default for national user. KPI strip; regional performance map; regional scorecard; AI performance insights; monthly/multi-year trends; downloads. Clicking a region updates scope or drills into the regional view.

- Header must show current geography, programme, period and comparison period where relevant.

- All data requests must inherit server-side authorisation and cannot be widened by front-end state.

- Clicking a scorecard cell opens indicator evidence rather than a generic modal.

- Charts and tables should be exportable with the same filters as the screen.

- Loading, no-data, stale-data and permission-denied states must be explicitly designed.

## 9.3 Regional/sub-regional overview

KPI strip for selected region; district map; district scorecard; priority insights; trends; top priority districts. Rows are districts/cities.

- Header must show current geography, programme, period and comparison period where relevant.

- All data requests must inherit server-side authorisation and cannot be widened by front-end state.

- Clicking a scorecard cell opens indicator evidence rather than a generic modal.

- Charts and tables should be exportable with the same filters as the screen.

- Loading, no-data, stale-data and permission-denied states must be explicitly designed.

## 9.4 District facility-performance view

Scope set to a district. Main table compares facilities with RAG indicator values and overall status; insight panel identifies strong and weak facilities; lower section shows facility trends and top/bottom performers.

- Header must show current geography, programme, period and comparison period where relevant.

- All data requests must inherit server-side authorisation and cannot be widened by front-end state.

- Clicking a scorecard cell opens indicator evidence rather than a generic modal.

- Charts and tables should be exportable with the same filters as the screen.

- Loading, no-data, stale-data and permission-denied states must be explicitly designed.

## 9.5 Sub-county facility-performance view

Same analytical pattern as district but limited to facilities in selected sub-county. If population-based facility indicators are requested, missing catchment populations are clearly flagged.

- Header must show current geography, programme, period and comparison period where relevant.

- All data requests must inherit server-side authorisation and cannot be widened by front-end state.

- Clicking a scorecard cell opens indicator evidence rather than a generic modal.

- Charts and tables should be exportable with the same filters as the screen.

- Loading, no-data, stale-data and permission-denied states must be explicitly designed.

## 9.6 Individual facility profile

Facility metadata; editable/approved catchment population; KPI cards; monthly trends; scorecard; data-quality alerts; AI summary; Excel/PPTX/report downloads.

- Header must show current geography, programme, period and comparison period where relevant.

- All data requests must inherit server-side authorisation and cannot be widened by front-end state.

- Clicking a scorecard cell opens indicator evidence rather than a generic modal.

- Charts and tables should be exportable with the same filters as the screen.

- Loading, no-data, stale-data and permission-denied states must be explicitly designed.

## 9.7 ANC workspace

Detailed ANC scorecard, continuum, year comparison, trends, map, denominator explanations and facility/district contribution analysis.

- Header must show current geography, programme, period and comparison period where relevant.

- All data requests must inherit server-side authorisation and cannot be widened by front-end state.

- Clicking a scorecard cell opens indicator evidence rather than a generic modal.

- Charts and tables should be exportable with the same filters as the screen.

- Loading, no-data, stale-data and permission-denied states must be explicitly designed.

## 9.8 Intrapartum/newborn workspace

Delivery, C-section, KMC, resuscitation and mortality outcomes with correct units/directions; year comparison and outcome trends.

- Header must show current geography, programme, period and comparison period where relevant.

- All data requests must inherit server-side authorisation and cannot be widened by front-end state.

- Clicking a scorecard cell opens indicator evidence rather than a generic modal.

- Charts and tables should be exportable with the same filters as the screen.

- Loading, no-data, stale-data and permission-denied states must be explicitly designed.

## 9.9 Immunization workspace

Antigen coverage, MV1-MV4, dropout, continuum, monthly target progress, zero/low-performing units and maps.

- Header must show current geography, programme, period and comparison period where relevant.

- All data requests must inherit server-side authorisation and cannot be widened by front-end state.

- Clicking a scorecard cell opens indicator evidence rather than a generic modal.

- Charts and tables should be exportable with the same filters as the screen.

- Loading, no-data, stale-data and permission-denied states must be explicitly designed.

## 9.10 MPDSR workspace

Combined perinatal/maternal notification-review scorecard; quarterly process performance; causes; active events; timeliness and reconciliation quality.

- Header must show current geography, programme, period and comparison period where relevant.

- All data requests must inherit server-side authorisation and cannot be widened by front-end state.

- Clicking a scorecard cell opens indicator evidence rather than a generic modal.

- Charts and tables should be exportable with the same filters as the screen.

- Loading, no-data, stale-data and permission-denied states must be explicitly designed.

## 9.11 Maps workspace

Indicator selector; level-aware boundaries; RAG legend; hover tooltip; click-to-drill; GeoJSON administration and no-data state.

- Header must show current geography, programme, period and comparison period where relevant.

- All data requests must inherit server-side authorisation and cannot be widened by front-end state.

- Clicking a scorecard cell opens indicator evidence rather than a generic modal.

- Charts and tables should be exportable with the same filters as the screen.

- Loading, no-data, stale-data and permission-denied states must be explicitly designed.

## 9.12 Trends workspace

Select indicators, periods and comparison geographies; monthly/quarterly/multi-year plots; anomalies; export chart/data.

- Header must show current geography, programme, period and comparison period where relevant.

- All data requests must inherit server-side authorisation and cannot be widened by front-end state.

- Clicking a scorecard cell opens indicator evidence rather than a generic modal.

- Charts and tables should be exportable with the same filters as the screen.

- Loading, no-data, stale-data and permission-denied states must be explicitly designed.

## 9.13 Data Quality workspace

Filter flags by severity, programme, unit, rule and period; show evidence and resolution status; permit authorised notes/resolution workflow.

- Header must show current geography, programme, period and comparison period where relevant.

- All data requests must inherit server-side authorisation and cannot be widened by front-end state.

- Clicking a scorecard cell opens indicator evidence rather than a generic modal.

- Charts and tables should be exportable with the same filters as the screen.

- Loading, no-data, stale-data and permission-denied states must be explicitly designed.

## 9.14 AI Insights / Ask the Data

Natural-language questions over authorised verified evidence; suggested questions; evidence citations; no raw unrestricted database access by LLM.

- Header must show current geography, programme, period and comparison period where relevant.

- All data requests must inherit server-side authorisation and cannot be widened by front-end state.

- Clicking a scorecard cell opens indicator evidence rather than a generic modal.

- Charts and tables should be exportable with the same filters as the screen.

- Loading, no-data, stale-data and permission-denied states must be explicitly designed.

## 9.15 Reports and Exports

Saved templates, generated files, generation status, period/geography selection and reproducible calculation-run reference.

- Header must show current geography, programme, period and comparison period where relevant.

- All data requests must inherit server-side authorisation and cannot be widened by front-end state.

- Clicking a scorecard cell opens indicator evidence rather than a generic modal.

- Charts and tables should be exportable with the same filters as the screen.

- Loading, no-data, stale-data and permission-denied states must be explicitly designed.

## 9.16 Administration

Users/roles, organisation mappings, populations, indicator versions, DHIS2 UIDs, GeoJSON, AI provider, templates and audit log.

- Header must show current geography, programme, period and comparison period where relevant.

- All data requests must inherit server-side authorisation and cannot be widened by front-end state.

- Clicking a scorecard cell opens indicator evidence rather than a generic modal.

- Charts and tables should be exportable with the same filters as the screen.

- Loading, no-data, stale-data and permission-denied states must be explicitly designed.

# 10. AI Intelligence Layer and Evidence-Safe Generation

AI is embedded, provider-flexible and useful - but never responsible for the arithmetic.

## 10.1 AI Gateway

The application should call an internal AI Gateway rather than hard-coding DeepSeek, OpenAI, Anthropic or another provider throughout the codebase. The gateway accepts a structured task and evidence package, selects the configured provider/model, applies privacy rules, logs token/cost metadata and returns a structured response. This allows inexpensive models to handle routine summaries while stronger models can be assigned to complex cross-indicator reasoning when approved.

## 10.2 Supported AI tasks

- Generate three concise findings for the current dashboard scope.

- Explain why a selected indicator is red or blue using the underlying evidence package.

- Answer authorised “Ask the Data” questions by combining deterministic query results with natural-language explanation.

- Draft management briefs, district feedback notes and presentation narratives.

- Generate recommendations that are explicitly tied to observed gaps and data-quality issues.

- Summarise cross-indicator patterns such as strong ANC1 access but poor ANC8 continuation.

- Explain changes over time and name the child units contributing most to the change.

## 10.3 Sensitive MPDSR handling

Raw maternal death narratives, names, patient identifiers, exact dates combined with rare causes, reviewer usernames and other identifying fields should not be sent to external AI providers. The deterministic backend should reduce line-list data to approved regional/national aggregates and broad structured cause/delay statistics before AI generation. If the platform later uses a self-hosted model under an approved governance arrangement, additional use cases can be enabled without changing the core privacy policy.

## 10.4 Hallucination controls

AI responses should be grounded in a structured evidence object containing only values the deterministic engine has calculated. The prompt should instruct the model not to invent missing values or causes. The returned response should be schema-validated; statements containing unsupported numbers should be rejected or regenerated. Where possible, each insight in the UI should link back to the underlying evidence view.

## 10.5 No-AI mode

The platform must remain fully functional if all AI providers are disabled. Deterministic rule-based narratives can still produce basic findings such as target achievement, largest improvement, largest deterioration, top contributors and data-quality alerts. AI enhances interpretation; it is not a dependency for core analytics, exports or access control.

# 11. Excel, PowerPoint and Narrative Report Generation

Exports must look approved every time and must be tied to a reproducible calculation run.

## 11.1 Excel export

Excel generation should be deterministic using an approved workbook design. A standard export should contain at least Scorecard, Calculations, Raw Data, Population, Methodology and Data Quality sheets. The Scorecard reproduces the on-screen RAG colours. Calculations expose numerator, denominator, exact value and status. Raw Data preserves source values required for audit. Population identifies the population version and year. Methodology lists formulas and thresholds. Data Quality lists all flags for the selected scope.

## 11.2 PowerPoint generation

PowerPoint should be generated from approved slide templates, not designed from scratch by the LLM. Templates correspond to repeatable slide patterns: current-period scorecard, year-on-year comparison, map plus insights, trend plus composition, district facility comparison, MPDSR process scorecard and clinical deep dive. The calculation/publishing engine populates tables, charts and colours. AI may write a small number of findings that fit designated text regions.

This separation is essential because the user expects downloaded PowerPoint slides to look exactly like the approved visual family. Random AI slide generation would produce inconsistent spacing, colours and layouts. Templates should therefore be versioned, previewable and managed by administrators.

## 11.3 Narrative report

Reports can be generated as Word/PDF using deterministic section templates and AI-written prose grounded in the evidence package. Recommended structure: executive summary; methodology; key performance results; year comparison; geographic inequities; data quality; programme-specific findings; priority actions; appendices. Every report should record geography, period, extraction time, indicator version set and calculation-run ID.

## 11.4 Reproducibility

All generated files must reference the same calculation run used to render the dashboard at the time of generation. If upstream data change after the export, the historical export should still be reproducible from stored run inputs or snapshots according to retention policy. This is especially important for official performance-review presentations where figures may later be questioned.

# 12. Technical Architecture, Database, APIs and Background Jobs

Implementation-level context for the IDE.

## 12.1 Recommended stack

| **Layer**  | **Recommended implementation**                           | **Reason**                                                    |
|------------|----------------------------------------------------------|---------------------------------------------------------------|
| Frontend   | React / Next.js + TypeScript                             | Strong component model, routing, state and production tooling |
| UI         | Tailwind + disciplined component library                 | Fast consistent recreation of approved dashboard design       |
| Charts     | Apache ECharts or Plotly                                 | Rich interactive analytical charts                            |
| Maps       | MapLibre GL or Leaflet                                   | GeoJSON, drill-down and performant map interactions           |
| Backend    | Python FastAPI or Flask API-first service                | Fits existing Python expertise and analytics workload         |
| Database   | PostgreSQL + PostGIS                                     | Relational configuration plus spatial data                    |
| Jobs       | Celery/RQ or equivalent                                  | DHIS2 sync, exports and AI generation                         |
| Cache      | Redis                                                    | Job broker and cached analytical results                      |
| Excel      | openpyxl                                                 | Deterministic styled workbooks                                |
| PowerPoint | PptxGenJS or python-pptx                                 | Template-driven PPTX generation                               |
| AI         | Gateway supporting DeepSeek/OpenAI/Anthropic/self-hosted | Provider flexibility and cost control                         |

## 12.2 Core tables

| **Table**                 | **Purpose**                                  |
|---------------------------|----------------------------------------------|
| users                     | Authentication identity and profile metadata |
| roles                     | Reusable role definitions                    |
| user_geography_scope      | Authorised org units                         |
| user_programme_scope      | Authorised programmes                        |
| user_permissions          | Action capabilities                          |
| org_units                 | Analytical geography hierarchy               |
| org_unit_mappings         | DHIS2 UID and external mappings              |
| geometries                | GeoJSON/PostGIS polygons or facility points  |
| population_versions       | Source/version metadata                      |
| population_values         | Org unit x year values                       |
| programmes                | Programme catalogue                          |
| indicators                | Canonical indicator identities               |
| indicator_versions        | Formula/target versions                      |
| indicator_source_mappings | DHIS2 data-element/program mappings          |
| raw_aggregate_values      | Normalised aggregate extracts                |
| raw_event_snapshots       | Approved event fields/snapshots              |
| calculation_runs          | Reproducible run header                      |
| calculated_values         | Indicator outputs by org unit/period         |
| data_quality_flags        | Rule-based issues                            |
| saved_views               | User analytical bookmarks                    |
| export_jobs               | Excel/PPTX/report generation                 |
| ai_requests               | Evidence-safe AI request log                 |
| audit_log                 | Configuration/security change history        |

## 12.3 Application API surface

| **Endpoint**                 | **Purpose**                                                       |
|------------------------------|-------------------------------------------------------------------|
| GET /me/context              | Return highest authorised geography, programme/action permissions |
| GET /org-units/{id}/children | Authorised child units                                            |
| GET /populations             | Resolve population by unit/year/version                           |
| POST /populations/override   | Authorised facility population entry                              |
| GET /indicators              | Indicator metadata available to user                              |
| GET /analytics/scorecard     | Calculated scorecard for geography/period/module                  |
| GET /analytics/trends        | Time series for selected indicators                               |
| GET /analytics/map           | Geo features + indicator values/status                            |
| GET /analytics/contribution  | Child-unit contribution/Pareto evidence                           |
| GET /quality/flags           | Data-quality issues                                               |
| GET /mpdsr/process           | Notification/review process analytics                             |
| POST /ai/explain             | Evidence-grounded explanation                                     |
| POST /ai/report              | Generate narrative from evidence package                          |
| POST /exports/excel          | Queue Excel export                                                |
| POST /exports/powerpoint     | Queue PPTX export                                                 |
| POST /exports/report         | Queue narrative report                                            |
| GET /jobs/{id}               | Background-job status                                             |

## 12.4 Background jobs

Background workers should perform DHIS2 synchronisation, metadata refresh, population imports, recalculation, anomaly scans, Excel generation, PowerPoint generation, narrative reports and large AI tasks. Each job should be idempotent where possible, record input parameters and emit structured logs. Long-running export operations should return a job ID immediately so the web request does not time out.

## 12.5 Observability

Production monitoring should include upstream DHIS2 latency/error rate, sync freshness, calculation failures, job queue depth, export failures, AI provider errors/cost, database slow queries and permission-denied events. User-facing error messages should be clear and should not expose secrets or stack traces. Administrators should have a system-health view separate from programme data quality.

# 13. Security, Privacy, Governance and Data Retention

Particularly important for MPDSR and role-based national deployment.

## 13.1 Authentication and sessions

Authentication may use platform accounts, institutional SSO or DHIS2-linked identity depending deployment constraints. Authentication identifies the user; authorisation is still enforced independently by the platform. Use secure session/cookie or token patterns, MFA for administrators if available, short-lived credentials and server-side permission checks.

## 13.2 Least privilege and query enforcement

Every endpoint that returns analytical data must resolve the caller's geography and programme scope before querying. The front end hiding a district is not security. The query itself must be restricted to authorised organisation units. Bulk exports and AI evidence queries require the same checks as interactive dashboards.

## 13.3 MPDSR privacy

Maternal death review data can contain highly sensitive narratives and small-number combinations. The platform should store only the minimum event fields required for the analytical functions, or maintain a protected event cache with strict access and encryption. Default dashboards should aggregate causes at a safe level. Exact event records should be available only to specifically authorised users and should not be copied into general-purpose logs.

## 13.4 Export governance

Exports can create new disclosure risks because files leave the web application. The system should respect programme and geography permissions during generation and may require additional restrictions for line-list exports. Presentation/report outputs should favour aggregated clinical information. Each generated file should record who generated it, scope, period and calculation run.

## 13.5 AI governance

The AI Gateway should have task-level policies defining which evidence fields may be sent to each provider. Public/aggregate indicators can use inexpensive external APIs. Sensitive MPDSR prompts should use de-identified aggregates, a specifically approved provider or a self-hosted model. Provider prompts/responses should not be retained indefinitely by the application unless governance requires it.

# 14. Validation, Regression Testing and Acceptance Criteria

Manual calculations already completed for Acholi become gold-standard tests for the engine.

## 14.1 Testing philosophy

The first goal of testing is not visual polish; it is proving that the new engine reproduces known calculations. The manually validated Acholi analyses should become regression fixtures. Any code change affecting denominators, period handling, aggregation or event status must rerun these fixtures. A visually attractive dashboard with a different number is a failed build.

| **Regression test**                     | **Calculation**                   | **Expected**     |
|-----------------------------------------|-----------------------------------|------------------|
| ANC1 Acholi FY2024/25                   | 99,510 / (2,044,355 x 5%) x100    | 97.4%            |
| ANC1 Acholi FY2025/26                   | 102,722 / (2,152,700 x 5%) x100   | 95.4%            |
| Institutional delivery Acholi FY2024/25 | 70,782 / (2,044,355 x 4.85%) x100 | 71.4%            |
| Institutional delivery Acholi FY2025/26 | 70,598 / (2,152,700 x 4.85%) x100 | 67.6%            |
| PMR Acholi FY2025/26                    | (420+464+557)/70,598 x1000        | 20.4 per 1,000   |
| MMR Acholi FY2025/26                    | 56 / 69,893 x100,000              | 80.1 per 100,000 |
| Perinatal notification coverage         | 1,125/1,441 x100                  | 78.1%            |
| Perinatal timely notification           | 931/1,441 x100                    | 64.6%            |
| Perinatal review coverage               | 1,064/1,441 x100                  | 73.8%            |
| Perinatal timely review                 | 766/1,441 x100                    | 53.2%            |
| Maternal notification coverage          | 52/56 x100                        | 92.9%            |
| Maternal timely notification            | 37/56 x100                        | 66.1%            |
| Maternal review coverage                | 53/56 x100                        | 94.6%            |
| Maternal review within 7 days           | 43/56 x100                        | 76.8%            |

## 14.2 Permission tests

- A district user requesting a sibling district by URL receives access denied and no data payload.

- A facility user can view only the authorised facility and cannot enumerate district facilities unless separately allowed.

- An export job applies the same geography/programme restrictions as the dashboard endpoint.

- An AI request cannot request evidence outside the user's authorised geography.

- Administrator endpoints require explicit administrative permission regardless of geography.

## 14.3 Population tests

- FY2024/25 resolves to 2024 population under current MNCH rule; FY2025/26 resolves to 2025.

- Quarterly immunisation target uses annual population x coefficient x 3/12.

- Facility population missing affects only population-derived indicators; service-derived indicators still calculate.

- Changing an approved facility population creates a new version/audit event rather than silently altering historical runs.

## 14.4 Export tests

Excel and PowerPoint values must exactly match the dashboard calculation run. RAG colours must match threshold rules. Count columns remain neutral. PMR/MMR must preserve rate units. Generated PowerPoint slides should follow approved templates at national, regional, district-facility and MPDSR levels. Automated visual regression can compare key template screenshots where practical.

# 15. Implementation Plan: Seven Phases and Twenty-Six Detailed Prompts

How to move from this blueprint to a production MNCH v1 without losing architecture.

| **Phase**                              | **Prompts** | **Primary result**                                                                                                      |
|----------------------------------------|-------------|-------------------------------------------------------------------------------------------------------------------------|
| Phase 1 - Architecture and Foundations | 3           | Master architecture; database/domain model; authentication/authorisation.                                               |
| Phase 2 - Data and Calculation Engines | 5           | DHIS2 aggregate connector; event/tracker connector; geography/population engine; indicator engine; data-quality engine. |
| Phase 3 - MNCH Analytical Modules      | 4           | ANC; intrapartum/newborn; immunisation/child health; MPDSR.                                                             |
| Phase 4 - Dashboard Experience         | 6           | Design system; national; regional; district facility comparison; facility profile; maps/trends workspaces.              |
| Phase 5 - AI Intelligence              | 2           | AI Gateway; AI analyst/Ask the Data.                                                                                    |
| Phase 6 - Publishing                   | 3           | Excel; PowerPoint; narrative report.                                                                                    |
| Phase 7 - Hardening and Production     | 3           | Regression testing; security/performance; deployment/documentation.                                                     |

## 15.1 Prompt-writing contract

Each implementation prompt should be approximately 1,300-1,500 words, focused on one coherent deliverable, and should include: context from this blueprint, exact files/modules to touch, data contracts, required behaviour, non-negotiables, acceptance tests, explicit exclusions and handoff requirements. A prompt should not ask the IDE to “build the whole dashboard”; it should produce a bounded, testable increment that composes with previous phases.

### 15.2 Prompt 1: Master Application Architecture

This prompt should implement Master Application Architecture as a production-quality increment while preserving all relevant rules in this blueprint. It must begin by inspecting the existing repository and prior phase outputs rather than replacing working architecture. It should finish with automated tests, a concise change log, unresolved decisions, and explicit confirmation that previously passing regression tests remain green.

- Do not change indicator formulas or thresholds outside administrator-configured versions.

- Do not loosen permission checks for convenience.

- Do not make AI responsible for deterministic calculations.

- Do not redesign approved UI patterns unless the prompt explicitly concerns the design system.

- Document migrations/configuration introduced by the prompt.

### 15.3 Prompt 2: Database and Domain Model

This prompt should implement Database and Domain Model as a production-quality increment while preserving all relevant rules in this blueprint. It must begin by inspecting the existing repository and prior phase outputs rather than replacing working architecture. It should finish with automated tests, a concise change log, unresolved decisions, and explicit confirmation that previously passing regression tests remain green.

- Do not change indicator formulas or thresholds outside administrator-configured versions.

- Do not loosen permission checks for convenience.

- Do not make AI responsible for deterministic calculations.

- Do not redesign approved UI patterns unless the prompt explicitly concerns the design system.

- Document migrations/configuration introduced by the prompt.

### 15.4 Prompt 3: Authentication and Authorisation

This prompt should implement Authentication and Authorisation as a production-quality increment while preserving all relevant rules in this blueprint. It must begin by inspecting the existing repository and prior phase outputs rather than replacing working architecture. It should finish with automated tests, a concise change log, unresolved decisions, and explicit confirmation that previously passing regression tests remain green.

- Do not change indicator formulas or thresholds outside administrator-configured versions.

- Do not loosen permission checks for convenience.

- Do not make AI responsible for deterministic calculations.

- Do not redesign approved UI patterns unless the prompt explicitly concerns the design system.

- Document migrations/configuration introduced by the prompt.

### 15.5 Prompt 4: DHIS2 Aggregate Connector

This prompt should implement DHIS2 Aggregate Connector as a production-quality increment while preserving all relevant rules in this blueprint. It must begin by inspecting the existing repository and prior phase outputs rather than replacing working architecture. It should finish with automated tests, a concise change log, unresolved decisions, and explicit confirmation that previously passing regression tests remain green.

- Do not change indicator formulas or thresholds outside administrator-configured versions.

- Do not loosen permission checks for convenience.

- Do not make AI responsible for deterministic calculations.

- Do not redesign approved UI patterns unless the prompt explicitly concerns the design system.

- Document migrations/configuration introduced by the prompt.

### 15.6 Prompt 5: DHIS2 Event/Tracker Connector

This prompt should implement DHIS2 Event/Tracker Connector as a production-quality increment while preserving all relevant rules in this blueprint. It must begin by inspecting the existing repository and prior phase outputs rather than replacing working architecture. It should finish with automated tests, a concise change log, unresolved decisions, and explicit confirmation that previously passing regression tests remain green.

- Do not change indicator formulas or thresholds outside administrator-configured versions.

- Do not loosen permission checks for convenience.

- Do not make AI responsible for deterministic calculations.

- Do not redesign approved UI patterns unless the prompt explicitly concerns the design system.

- Document migrations/configuration introduced by the prompt.

### 15.7 Prompt 6: National Geography and Population Engine

This prompt should implement National Geography and Population Engine as a production-quality increment while preserving all relevant rules in this blueprint. It must begin by inspecting the existing repository and prior phase outputs rather than replacing working architecture. It should finish with automated tests, a concise change log, unresolved decisions, and explicit confirmation that previously passing regression tests remain green.

- Do not change indicator formulas or thresholds outside administrator-configured versions.

- Do not loosen permission checks for convenience.

- Do not make AI responsible for deterministic calculations.

- Do not redesign approved UI patterns unless the prompt explicitly concerns the design system.

- Document migrations/configuration introduced by the prompt.

### 15.8 Prompt 7: Indicator Calculation Engine

This prompt should implement Indicator Calculation Engine as a production-quality increment while preserving all relevant rules in this blueprint. It must begin by inspecting the existing repository and prior phase outputs rather than replacing working architecture. It should finish with automated tests, a concise change log, unresolved decisions, and explicit confirmation that previously passing regression tests remain green.

- Do not change indicator formulas or thresholds outside administrator-configured versions.

- Do not loosen permission checks for convenience.

- Do not make AI responsible for deterministic calculations.

- Do not redesign approved UI patterns unless the prompt explicitly concerns the design system.

- Document migrations/configuration introduced by the prompt.

### 15.9 Prompt 8: Data Quality Engine

This prompt should implement Data Quality Engine as a production-quality increment while preserving all relevant rules in this blueprint. It must begin by inspecting the existing repository and prior phase outputs rather than replacing working architecture. It should finish with automated tests, a concise change log, unresolved decisions, and explicit confirmation that previously passing regression tests remain green.

- Do not change indicator formulas or thresholds outside administrator-configured versions.

- Do not loosen permission checks for convenience.

- Do not make AI responsible for deterministic calculations.

- Do not redesign approved UI patterns unless the prompt explicitly concerns the design system.

- Document migrations/configuration introduced by the prompt.

### 15.10 Prompt 9: ANC Module

This prompt should implement ANC Module as a production-quality increment while preserving all relevant rules in this blueprint. It must begin by inspecting the existing repository and prior phase outputs rather than replacing working architecture. It should finish with automated tests, a concise change log, unresolved decisions, and explicit confirmation that previously passing regression tests remain green.

- Do not change indicator formulas or thresholds outside administrator-configured versions.

- Do not loosen permission checks for convenience.

- Do not make AI responsible for deterministic calculations.

- Do not redesign approved UI patterns unless the prompt explicitly concerns the design system.

- Document migrations/configuration introduced by the prompt.

### 15.11 Prompt 10: Intrapartum and Newborn Module

This prompt should implement Intrapartum and Newborn Module as a production-quality increment while preserving all relevant rules in this blueprint. It must begin by inspecting the existing repository and prior phase outputs rather than replacing working architecture. It should finish with automated tests, a concise change log, unresolved decisions, and explicit confirmation that previously passing regression tests remain green.

- Do not change indicator formulas or thresholds outside administrator-configured versions.

- Do not loosen permission checks for convenience.

- Do not make AI responsible for deterministic calculations.

- Do not redesign approved UI patterns unless the prompt explicitly concerns the design system.

- Document migrations/configuration introduced by the prompt.

### 15.12 Prompt 11: Immunisation and Child Health Module

This prompt should implement Immunisation and Child Health Module as a production-quality increment while preserving all relevant rules in this blueprint. It must begin by inspecting the existing repository and prior phase outputs rather than replacing working architecture. It should finish with automated tests, a concise change log, unresolved decisions, and explicit confirmation that previously passing regression tests remain green.

- Do not change indicator formulas or thresholds outside administrator-configured versions.

- Do not loosen permission checks for convenience.

- Do not make AI responsible for deterministic calculations.

- Do not redesign approved UI patterns unless the prompt explicitly concerns the design system.

- Document migrations/configuration introduced by the prompt.

### 15.13 Prompt 12: MPDSR Module

This prompt should implement MPDSR Module as a production-quality increment while preserving all relevant rules in this blueprint. It must begin by inspecting the existing repository and prior phase outputs rather than replacing working architecture. It should finish with automated tests, a concise change log, unresolved decisions, and explicit confirmation that previously passing regression tests remain green.

- Do not change indicator formulas or thresholds outside administrator-configured versions.

- Do not loosen permission checks for convenience.

- Do not make AI responsible for deterministic calculations.

- Do not redesign approved UI patterns unless the prompt explicitly concerns the design system.

- Document migrations/configuration introduced by the prompt.

### 15.14 Prompt 13: Global UI Design System

This prompt should implement Global UI Design System as a production-quality increment while preserving all relevant rules in this blueprint. It must begin by inspecting the existing repository and prior phase outputs rather than replacing working architecture. It should finish with automated tests, a concise change log, unresolved decisions, and explicit confirmation that previously passing regression tests remain green.

- Do not change indicator formulas or thresholds outside administrator-configured versions.

- Do not loosen permission checks for convenience.

- Do not make AI responsible for deterministic calculations.

- Do not redesign approved UI patterns unless the prompt explicitly concerns the design system.

- Document migrations/configuration introduced by the prompt.

### 15.15 Prompt 14: National Dashboard

This prompt should implement National Dashboard as a production-quality increment while preserving all relevant rules in this blueprint. It must begin by inspecting the existing repository and prior phase outputs rather than replacing working architecture. It should finish with automated tests, a concise change log, unresolved decisions, and explicit confirmation that previously passing regression tests remain green.

- Do not change indicator formulas or thresholds outside administrator-configured versions.

- Do not loosen permission checks for convenience.

- Do not make AI responsible for deterministic calculations.

- Do not redesign approved UI patterns unless the prompt explicitly concerns the design system.

- Document migrations/configuration introduced by the prompt.

### 15.16 Prompt 15: Regional Dashboard

This prompt should implement Regional Dashboard as a production-quality increment while preserving all relevant rules in this blueprint. It must begin by inspecting the existing repository and prior phase outputs rather than replacing working architecture. It should finish with automated tests, a concise change log, unresolved decisions, and explicit confirmation that previously passing regression tests remain green.

- Do not change indicator formulas or thresholds outside administrator-configured versions.

- Do not loosen permission checks for convenience.

- Do not make AI responsible for deterministic calculations.

- Do not redesign approved UI patterns unless the prompt explicitly concerns the design system.

- Document migrations/configuration introduced by the prompt.

### 15.17 Prompt 16: District Facility Performance Dashboard

This prompt should implement District Facility Performance Dashboard as a production-quality increment while preserving all relevant rules in this blueprint. It must begin by inspecting the existing repository and prior phase outputs rather than replacing working architecture. It should finish with automated tests, a concise change log, unresolved decisions, and explicit confirmation that previously passing regression tests remain green.

- Do not change indicator formulas or thresholds outside administrator-configured versions.

- Do not loosen permission checks for convenience.

- Do not make AI responsible for deterministic calculations.

- Do not redesign approved UI patterns unless the prompt explicitly concerns the design system.

- Document migrations/configuration introduced by the prompt.

### 15.18 Prompt 17: Individual Facility Dashboard

This prompt should implement Individual Facility Dashboard as a production-quality increment while preserving all relevant rules in this blueprint. It must begin by inspecting the existing repository and prior phase outputs rather than replacing working architecture. It should finish with automated tests, a concise change log, unresolved decisions, and explicit confirmation that previously passing regression tests remain green.

- Do not change indicator formulas or thresholds outside administrator-configured versions.

- Do not loosen permission checks for convenience.

- Do not make AI responsible for deterministic calculations.

- Do not redesign approved UI patterns unless the prompt explicitly concerns the design system.

- Document migrations/configuration introduced by the prompt.

### 15.19 Prompt 18: Maps and Geographic Intelligence

This prompt should implement Maps and Geographic Intelligence as a production-quality increment while preserving all relevant rules in this blueprint. It must begin by inspecting the existing repository and prior phase outputs rather than replacing working architecture. It should finish with automated tests, a concise change log, unresolved decisions, and explicit confirmation that previously passing regression tests remain green.

- Do not change indicator formulas or thresholds outside administrator-configured versions.

- Do not loosen permission checks for convenience.

- Do not make AI responsible for deterministic calculations.

- Do not redesign approved UI patterns unless the prompt explicitly concerns the design system.

- Document migrations/configuration introduced by the prompt.

### 15.20 Prompt 19: AI Gateway

This prompt should implement AI Gateway as a production-quality increment while preserving all relevant rules in this blueprint. It must begin by inspecting the existing repository and prior phase outputs rather than replacing working architecture. It should finish with automated tests, a concise change log, unresolved decisions, and explicit confirmation that previously passing regression tests remain green.

- Do not change indicator formulas or thresholds outside administrator-configured versions.

- Do not loosen permission checks for convenience.

- Do not make AI responsible for deterministic calculations.

- Do not redesign approved UI patterns unless the prompt explicitly concerns the design system.

- Document migrations/configuration introduced by the prompt.

### 15.21 Prompt 20: AI Analyst and Ask the Data

This prompt should implement AI Analyst and Ask the Data as a production-quality increment while preserving all relevant rules in this blueprint. It must begin by inspecting the existing repository and prior phase outputs rather than replacing working architecture. It should finish with automated tests, a concise change log, unresolved decisions, and explicit confirmation that previously passing regression tests remain green.

- Do not change indicator formulas or thresholds outside administrator-configured versions.

- Do not loosen permission checks for convenience.

- Do not make AI responsible for deterministic calculations.

- Do not redesign approved UI patterns unless the prompt explicitly concerns the design system.

- Document migrations/configuration introduced by the prompt.

### 15.22 Prompt 21: Excel Generator

This prompt should implement Excel Generator as a production-quality increment while preserving all relevant rules in this blueprint. It must begin by inspecting the existing repository and prior phase outputs rather than replacing working architecture. It should finish with automated tests, a concise change log, unresolved decisions, and explicit confirmation that previously passing regression tests remain green.

- Do not change indicator formulas or thresholds outside administrator-configured versions.

- Do not loosen permission checks for convenience.

- Do not make AI responsible for deterministic calculations.

- Do not redesign approved UI patterns unless the prompt explicitly concerns the design system.

- Document migrations/configuration introduced by the prompt.

### 15.23 Prompt 22: PowerPoint Generator

This prompt should implement PowerPoint Generator as a production-quality increment while preserving all relevant rules in this blueprint. It must begin by inspecting the existing repository and prior phase outputs rather than replacing working architecture. It should finish with automated tests, a concise change log, unresolved decisions, and explicit confirmation that previously passing regression tests remain green.

- Do not change indicator formulas or thresholds outside administrator-configured versions.

- Do not loosen permission checks for convenience.

- Do not make AI responsible for deterministic calculations.

- Do not redesign approved UI patterns unless the prompt explicitly concerns the design system.

- Document migrations/configuration introduced by the prompt.

### 15.24 Prompt 23: Narrative Report Generator

This prompt should implement Narrative Report Generator as a production-quality increment while preserving all relevant rules in this blueprint. It must begin by inspecting the existing repository and prior phase outputs rather than replacing working architecture. It should finish with automated tests, a concise change log, unresolved decisions, and explicit confirmation that previously passing regression tests remain green.

- Do not change indicator formulas or thresholds outside administrator-configured versions.

- Do not loosen permission checks for convenience.

- Do not make AI responsible for deterministic calculations.

- Do not redesign approved UI patterns unless the prompt explicitly concerns the design system.

- Document migrations/configuration introduced by the prompt.

### 15.25 Prompt 24: Full Regression and Validation

This prompt should implement Full Regression and Validation as a production-quality increment while preserving all relevant rules in this blueprint. It must begin by inspecting the existing repository and prior phase outputs rather than replacing working architecture. It should finish with automated tests, a concise change log, unresolved decisions, and explicit confirmation that previously passing regression tests remain green.

- Do not change indicator formulas or thresholds outside administrator-configured versions.

- Do not loosen permission checks for convenience.

- Do not make AI responsible for deterministic calculations.

- Do not redesign approved UI patterns unless the prompt explicitly concerns the design system.

- Document migrations/configuration introduced by the prompt.

### 15.26 Prompt 25: Security Performance and Reliability

This prompt should implement Security Performance and Reliability as a production-quality increment while preserving all relevant rules in this blueprint. It must begin by inspecting the existing repository and prior phase outputs rather than replacing working architecture. It should finish with automated tests, a concise change log, unresolved decisions, and explicit confirmation that previously passing regression tests remain green.

- Do not change indicator formulas or thresholds outside administrator-configured versions.

- Do not loosen permission checks for convenience.

- Do not make AI responsible for deterministic calculations.

- Do not redesign approved UI patterns unless the prompt explicitly concerns the design system.

- Document migrations/configuration introduced by the prompt.

### 15.27 Prompt 26: Production Deployment and Documentation

This prompt should implement Production Deployment and Documentation as a production-quality increment while preserving all relevant rules in this blueprint. It must begin by inspecting the existing repository and prior phase outputs rather than replacing working architecture. It should finish with automated tests, a concise change log, unresolved decisions, and explicit confirmation that previously passing regression tests remain green.

- Do not change indicator formulas or thresholds outside administrator-configured versions.

- Do not loosen permission checks for convenience.

- Do not make AI responsible for deterministic calculations.

- Do not redesign approved UI patterns unless the prompt explicitly concerns the design system.

- Document migrations/configuration introduced by the prompt.

# Appendix A. Internal Data Contracts

Canonical shapes the IDE should use between ingestion, calculation, analytics, AI and publishing.

## A.1 Raw aggregate value

| **Field**        | **Description**                                     |
|------------------|-----------------------------------------------------|
| source_system    | dhis2 / spreadsheet / approved external source      |
| org_unit_id      | Canonical internal geography ID                     |
| period           | Monthly/quarterly/FY canonical period key           |
| source_metric_id | Mapped DHIS2 data element/indicator or import field |
| value            | Raw numeric value                                   |
| extracted_at     | Timestamp of source extraction                      |
| source_version   | Metadata/snapshot reference                         |
| provenance       | Mapping/import lineage                              |

## A.2 Event record

| **Field**         | **Description**                        |
|-------------------|----------------------------------------|
| event_uid         | DHIS2 event UID where available        |
| program_uid       | Program identifier                     |
| program_stage_uid | Stage identifier                       |
| org_unit_id       | Canonical mapped facility/org unit     |
| status            | ACTIVE / COMPLETED / other valid state |
| occurred_at       | Event occurrence timestamp             |
| completed_at      | Completion timestamp if available      |
| death_date        | Semantic death date after mapping      |
| data_values       | Approved semantic event fields         |
| extracted_at      | Snapshot timestamp                     |
| privacy_class     | Sensitivity classification             |

## A.3 Calculated value

| **Field**             | **Description**                 |
|-----------------------|---------------------------------|
| calculation_run_id    | Reproducible run identifier     |
| indicator_version_id  | Exact formula/threshold version |
| org_unit_id           | Geography                       |
| period                | Analysis period                 |
| numerator             | Aggregated numerator            |
| denominator           | Resolved denominator            |
| raw_value             | Full-precision calculation      |
| display_value         | Rounded display                 |
| status                | Green/Yellow/Red/Blue/N/A       |
| quality_flags         | Related rule IDs                |
| population_version_id | Population provenance when used |

## A.4 AI evidence package

The AI evidence package should include only the facts needed for the requested task: current geography/period, indicator definitions, current/prior values, target/status, underlying numerator/denominator, trend summary, top contributors, relevant quality flags and permitted recommendations context. Sensitive raw event narratives are excluded by default. The evidence object should be serialisable and stored with the AI request so the generated text can later be audited against the facts supplied.

# Appendix B. Administration Requirements

What administrators must be able to configure without code changes.

- Create and version indicator definitions, coefficients, targets and colour bands.

- Map DHIS2 data elements, indicators, programs, stages and semantic event fields.

- Import population files and approve population versions by year.

- Enter or approve facility catchment populations and source notes.

- Upload/map GeoJSON or spatial features to organisation units.

- Create users/roles and assign geography, programme and action scopes.

- Configure AI providers, models, task routes, token budgets and sensitive-data policies.

- Upload/version Excel, PowerPoint and report templates.

- View sync status, calculation jobs, failed exports and audit logs.

- Mark data-quality flags resolved with appropriate user notes without deleting original evidence.

# Appendix C. Future Programme Expansion

How to add HIV, TB, malaria, nutrition, reporting and other programmes without rebuilding the platform.

A new aggregate programme should primarily require: programme registration, indicator definitions, target rules, DHIS2 metadata mappings, optional programme-specific charts and regression fixtures. The shared engines for permissions, geography, populations, trends, maps, exports, AI and data quality remain unchanged. A new event programme additionally requires event semantic mappings, sensitivity classification and programme-specific reconciliation/timeliness logic.

The current interface navigation should not display future programmes prematurely. MNCH, Immunization and MPDSR are the first-release emphasis. Later modules can be introduced through configuration/feature flags while preserving the same national-to-facility navigation and visual system.

# Appendix D. IDE Non-Negotiable Handoff Summary

Short checklist to keep visible while implementation prompts are executed.

- Highest authorised organisational unit is the landing page.

- Hierarchy supports Uganda -\> region/sub-region -\> district/city -\> sub-county -\> facility.

- Population is versioned by year/source; facility population may be entered when absent.

- FY2024/25 uses 2024 population and FY2025/26 uses 2025 under current MNCH rule.

- Expected pregnancies = 5% population; expected deliveries = 4.85%; infant immunisation target = 4.3%; MV4 = 4.3%.

- Aggregate numerator/denominator first; never average child percentages by default.

- Perinatal deaths = fresh stillbirths + macerated stillbirths + newborn deaths.

- Perinatal notification/review target \>=90% with green \>=90, yellow 75-89.9, red \<75.

- Maternal notification/review target 100% with green 100, yellow 90-99.9, red \<90.

- ACTIVE event = not completed. BLUE = data-quality/non-assessable state, not achievement.

- DHIS2 aggregate analytics plus Event Analytics/Tracker are both required for the complete architecture.

- AI receives verified evidence; deterministic code calculates indicators and generates file structures.

- PowerPoint and Excel are template-driven and reproducible.

- UI baseline is the approved blue/navy DHIS2-like format with only subtle natural background treatment.

- Every calculation, export and AI narrative must respect geography/programme/action permissions.

# Appendix E. Detailed Screen-by-Screen Product Contracts

This appendix turns the visual mock-ups into implementation contracts. The purpose is to remove ambiguity for the IDE: each screen has a defined audience, scope resolution, data dependencies, components, interactions, loading states, error states, AI behaviour, export behaviour and acceptance criteria. The layouts may adapt responsively, but the analytical hierarchy and interaction logic should remain stable.

## E.1 National Overview

Provide the highest-level picture for a user authorised to Uganda, with immediate access to national MNCH status and the ability to drill into regions/sub-regions.

### Scope resolution and data dependencies

The National Overview screen resolves the authenticated user first, then the requested geography and period, and only then loads indicator data. The server must confirm that the requested geography is equal to or below the user’s authorised root and that every requested indicator belongs to an authorised programme. Population-based measures resolve the population year from the configured financial-year rule; service-derived measures use source service counts; event-based measures query the relevant MPDSR calculation outputs. The screen should receive a single coherent calculation-run identifier so all cards, tables, charts and export actions represent the same analytical snapshot.

### Required visual components

- Global header with period, comparison period, programme and geography selectors

- Six to eight headline KPI cards selected from the active module

- National/regional choropleth map for a selected indicator or composite view

- Regional scorecard with rows for regions/sub-regions and columns for configured indicators

- AI Performance Insights panel with evidence-backed national findings

- Monthly or multi-year trend chart

- Download area for Excel, PowerPoint and report generation

### Interaction behaviour

- Changing period reruns calculations using period-appropriate populations and updates every component in one state transition.

- Clicking a region on the map changes the scope to that region if the user is authorised, preserving period and programme.

- Clicking a scorecard cell opens the evidence drawer containing formula, numerator, denominator, target, trend and child-unit contributions.

- The map indicator selector changes only the mapped measure unless the user chooses to use it as the active dashboard indicator.

- Generate brief creates an AI request from the current evidence package; it does not send unrestricted national raw data.

### Loading and refresh behaviour

Initial load should render the structural shell quickly, then populate data from cached/materialised analytics. A visible refresh timestamp must indicate data age. If a user changes geography, period or programme, cancel stale in-flight requests and render one consistent new state rather than mixing old and new values. Background refresh may update the cache, but the current screen should not silently change figures in the middle of an export or AI generation; those actions bind to the active calculation run.

### Error and edge states

- If some regions lack geometry, they remain in the scorecard and are listed as unmapped rather than disappearing.

- If an indicator has no approved target, show value and methodology but no invented RAG status.

- If the national population version is missing for a requested period, block only indicators that need it and show the reason.

### AI behaviour

AI content on this screen must be generated from the screen evidence package, which includes only the authorised calculated outputs, comparisons, contributions and approved quality flags required for the task. AI must not recalculate formulas, invent missing target values or infer individual causes from aggregate data. If AI is disabled or unavailable, deterministic findings such as target status, largest improvement/deterioration and leading contributors should still populate a basic insight panel.

### Export behaviour

Excel, PowerPoint and narrative-report actions must preserve the current geography, period, programme, comparison period and indicator configuration. Exports should use the same calculation-run ID and therefore exactly match the screen values. If an export template cannot accommodate all selected indicators, the system should use a documented overflow/continuation template rather than shrink text until unreadable.

### Acceptance criteria

- No value on this screen differs from the equivalent calculation API response.

- Changing scope never reveals unauthorised units.

- All red/blue cells can be explained through an evidence drawer.

- No-data and stale-data states are explicit and never silently converted to zero.

- The screen remains usable at common laptop resolutions and retains readable tables/charts for projection.

## E.2 Regional/Sub-regional Overview

Show district/city differences within a selected region, with enough detail to identify priority districts and then drill down.

### Scope resolution and data dependencies

The Regional/Sub-regional Overview screen resolves the authenticated user first, then the requested geography and period, and only then loads indicator data. The server must confirm that the requested geography is equal to or below the user’s authorised root and that every requested indicator belongs to an authorised programme. Population-based measures resolve the population year from the configured financial-year rule; service-derived measures use source service counts; event-based measures query the relevant MPDSR calculation outputs. The screen should receive a single coherent calculation-run identifier so all cards, tables, charts and export actions represent the same analytical snapshot.

### Required visual components

- Regional KPI cards

- District map

- District scorecard

- Priority insights

- Monthly trends

- Top priority district table with key issue and recommended action

### Interaction behaviour

- Selecting a district from map/table navigates to district facility-comparison screen.

- Compare period adds previous-year values and changes where space allows; detailed comparison may open a dedicated view.

- Top-priority ranking is deterministic and based on configured scoring, not AI opinion. AI explains the ranking after it is calculated.

### Loading and refresh behaviour

Initial load should render the structural shell quickly, then populate data from cached/materialised analytics. A visible refresh timestamp must indicate data age. If a user changes geography, period or programme, cancel stale in-flight requests and render one consistent new state rather than mixing old and new values. Background refresh may update the cache, but the current screen should not silently change figures in the middle of an export or AI generation; those actions bind to the active calculation run.

### Error and edge states

- Cities are treated as peer analytical units when configured at the district-equivalent level.

- Regional aggregate is calculated from summed numerators/denominators rather than average district percentages.

- High referral centres should trigger contextual caveats for mortality-burden comparisons where relevant.

### AI behaviour

AI content on this screen must be generated from the screen evidence package, which includes only the authorised calculated outputs, comparisons, contributions and approved quality flags required for the task. AI must not recalculate formulas, invent missing target values or infer individual causes from aggregate data. If AI is disabled or unavailable, deterministic findings such as target status, largest improvement/deterioration and leading contributors should still populate a basic insight panel.

### Export behaviour

Excel, PowerPoint and narrative-report actions must preserve the current geography, period, programme, comparison period and indicator configuration. Exports should use the same calculation-run ID and therefore exactly match the screen values. If an export template cannot accommodate all selected indicators, the system should use a documented overflow/continuation template rather than shrink text until unreadable.

### Acceptance criteria

- No value on this screen differs from the equivalent calculation API response.

- Changing scope never reveals unauthorised units.

- All red/blue cells can be explained through an evidence drawer.

- No-data and stale-data states are explicit and never silently converted to zero.

- The screen remains usable at common laptop resolutions and retains readable tables/charts for projection.

## E.3 District Facility Performance

Compare all authorised facilities in a selected district and identify which facilities drive district performance gaps or data-quality problems.

### Scope resolution and data dependencies

The District Facility Performance screen resolves the authenticated user first, then the requested geography and period, and only then loads indicator data. The server must confirm that the requested geography is equal to or below the user’s authorised root and that every requested indicator belongs to an authorised programme. Population-based measures resolve the population year from the configured financial-year rule; service-derived measures use source service counts; event-based measures query the relevant MPDSR calculation outputs. The screen should receive a single coherent calculation-run identifier so all cards, tables, charts and export actions represent the same analytical snapshot.

### Required visual components

- District KPI strip

- Large facility scorecard table with facility level and key indicators

- Facility insights panel

- Facility trend section

- Top/bottom facility ranking for selected indicator

- Downloads and district report action

### Interaction behaviour

- Indicator columns can be reordered/filtered but approved default presets are provided for ANC, intrapartum, EPI and MPDSR.

- Clicking a facility row opens the individual facility profile.

- Clicking an indicator header sorts/ranks facilities and updates top/bottom panel.

- Users can filter by facility level, ownership, sub-county and reporting status.

### Loading and refresh behaviour

Initial load should render the structural shell quickly, then populate data from cached/materialised analytics. A visible refresh timestamp must indicate data age. If a user changes geography, period or programme, cancel stale in-flight requests and render one consistent new state rather than mixing old and new values. Background refresh may update the cache, but the current screen should not silently change figures in the middle of an export or AI generation; those actions bind to the active calculation run.

### Error and edge states

- Facilities without population still show service-derived indicators and receive N/A only for affected population-derived coverage measures.

- Do not rank facilities on indicators with unresolved BLUE data-quality flags unless the user explicitly includes them.

- Small facility denominators should be shown where a percentage could be misleading.

### AI behaviour

AI content on this screen must be generated from the screen evidence package, which includes only the authorised calculated outputs, comparisons, contributions and approved quality flags required for the task. AI must not recalculate formulas, invent missing target values or infer individual causes from aggregate data. If AI is disabled or unavailable, deterministic findings such as target status, largest improvement/deterioration and leading contributors should still populate a basic insight panel.

### Export behaviour

Excel, PowerPoint and narrative-report actions must preserve the current geography, period, programme, comparison period and indicator configuration. Exports should use the same calculation-run ID and therefore exactly match the screen values. If an export template cannot accommodate all selected indicators, the system should use a documented overflow/continuation template rather than shrink text until unreadable.

### Acceptance criteria

- No value on this screen differs from the equivalent calculation API response.

- Changing scope never reveals unauthorised units.

- All red/blue cells can be explained through an evidence drawer.

- No-data and stale-data states are explicit and never silently converted to zero.

- The screen remains usable at common laptop resolutions and retains readable tables/charts for projection.

## E.4 Sub-county Facility Performance

Provide the same facility comparison pattern at sub-county scope, preserving district context and restricting facilities to that sub-county.

### Scope resolution and data dependencies

The Sub-county Facility Performance screen resolves the authenticated user first, then the requested geography and period, and only then loads indicator data. The server must confirm that the requested geography is equal to or below the user’s authorised root and that every requested indicator belongs to an authorised programme. Population-based measures resolve the population year from the configured financial-year rule; service-derived measures use source service counts; event-based measures query the relevant MPDSR calculation outputs. The screen should receive a single coherent calculation-run identifier so all cards, tables, charts and export actions represent the same analytical snapshot.

### Required visual components

- Sub-county metadata and parent district

- Facility scorecard

- Trend/ranking components

- Population completeness indicator for facilities

- Data-quality panel

### Interaction behaviour

- User can move to sibling sub-counties only if authorised at district level.

- Facility population editor is available only to users with population-edit permission.

- Map can show facility points when coordinates are available.

### Loading and refresh behaviour

Initial load should render the structural shell quickly, then populate data from cached/materialised analytics. A visible refresh timestamp must indicate data age. If a user changes geography, period or programme, cancel stale in-flight requests and render one consistent new state rather than mixing old and new values. Background refresh may update the cache, but the current screen should not silently change figures in the middle of an export or AI generation; those actions bind to the active calculation run.

### Error and edge states

- If a sub-county contains only one facility, ranking modules collapse and the screen behaves more like a facility summary.

- Population values entered at facility level must not alter sub-county official population totals unless a separate reconciliation process is approved.

### AI behaviour

AI content on this screen must be generated from the screen evidence package, which includes only the authorised calculated outputs, comparisons, contributions and approved quality flags required for the task. AI must not recalculate formulas, invent missing target values or infer individual causes from aggregate data. If AI is disabled or unavailable, deterministic findings such as target status, largest improvement/deterioration and leading contributors should still populate a basic insight panel.

### Export behaviour

Excel, PowerPoint and narrative-report actions must preserve the current geography, period, programme, comparison period and indicator configuration. Exports should use the same calculation-run ID and therefore exactly match the screen values. If an export template cannot accommodate all selected indicators, the system should use a documented overflow/continuation template rather than shrink text until unreadable.

### Acceptance criteria

- No value on this screen differs from the equivalent calculation API response.

- Changing scope never reveals unauthorised units.

- All red/blue cells can be explained through an evidence drawer.

- No-data and stale-data states are explicit and never silently converted to zero.

- The screen remains usable at common laptop resolutions and retains readable tables/charts for projection.

## E.5 Individual Facility Profile

Give a facility user or supervisor a complete, actionable profile without requiring spreadsheet calculations.

### Scope resolution and data dependencies

The Individual Facility Profile screen resolves the authenticated user first, then the requested geography and period, and only then loads indicator data. The server must confirm that the requested geography is equal to or below the user’s authorised root and that every requested indicator belongs to an authorised programme. Population-based measures resolve the population year from the configured financial-year rule; service-derived measures use source service counts; event-based measures query the relevant MPDSR calculation outputs. The screen should receive a single coherent calculation-run identifier so all cards, tables, charts and export actions represent the same analytical snapshot.

### Required visual components

- Facility metadata banner

- Catchment population panel with year/source/status

- KPI cards

- Monthly service trends

- Indicator scorecard with Value, Target and Status

- Data quality and alerts

- AI summary and recommended actions

- Excel/PPTX/facility report downloads

### Interaction behaviour

- Edit population opens a controlled form that records year, value, source and note; updates require permission.

- Indicator card opens methodology/evidence.

- Data-quality alert opens raw supporting facts allowed to the user.

- Generate report creates a facility-scoped report using only authorised evidence.

### Loading and refresh behaviour

Initial load should render the structural shell quickly, then populate data from cached/materialised analytics. A visible refresh timestamp must indicate data age. If a user changes geography, period or programme, cancel stale in-flight requests and render one consistent new state rather than mixing old and new values. Background refresh may update the cache, but the current screen should not silently change figures in the middle of an export or AI generation; those actions bind to the active calculation run.

### Error and edge states

- If population is absent, show a clear request only for population-derived indicators; do not disable the whole page.

- A facility may receive patients outside its catchment; \>100% expected-population coverage is retained and contextualised rather than automatically declared wrong.

- Sensitive MPDSR event details are not exposed merely because the user can view aggregate facility MNCH.

### AI behaviour

AI content on this screen must be generated from the screen evidence package, which includes only the authorised calculated outputs, comparisons, contributions and approved quality flags required for the task. AI must not recalculate formulas, invent missing target values or infer individual causes from aggregate data. If AI is disabled or unavailable, deterministic findings such as target status, largest improvement/deterioration and leading contributors should still populate a basic insight panel.

### Export behaviour

Excel, PowerPoint and narrative-report actions must preserve the current geography, period, programme, comparison period and indicator configuration. Exports should use the same calculation-run ID and therefore exactly match the screen values. If an export template cannot accommodate all selected indicators, the system should use a documented overflow/continuation template rather than shrink text until unreadable.

### Acceptance criteria

- No value on this screen differs from the equivalent calculation API response.

- Changing scope never reveals unauthorised units.

- All red/blue cells can be explained through an evidence drawer.

- No-data and stale-data states are explicit and never silently converted to zero.

- The screen remains usable at common laptop resolutions and retains readable tables/charts for projection.

## E.6 ANC Workspace

Provide deep ANC analysis beyond the overview scorecard, including access, quality, continuity and adolescent pregnancy.

### Scope resolution and data dependencies

The ANC Workspace screen resolves the authenticated user first, then the requested geography and period, and only then loads indicator data. The server must confirm that the requested geography is equal to or below the user’s authorised root and that every requested indicator belongs to an authorised programme. Population-based measures resolve the population year from the configured financial-year rule; service-derived measures use source service counts; event-based measures query the relevant MPDSR calculation outputs. The screen should receive a single coherent calculation-run identifier so all cards, tables, charts and export actions represent the same analytical snapshot.

### Required visual components

- ANC indicator scorecard

- ANC1-ANC4-ANC8 continuum

- Year-on-year comparison

- Monthly trends

- Map by selected ANC indicator

- Facility/district contribution to gap

- Methodology panel

### Interaction behaviour

- Continuum can switch between coverage against expected pregnancies and retention relative to ANC1 where appropriate.

- A selected red indicator can show facilities with largest absolute missed-target count, not only lowest percentages.

- Teenage pregnancy uses inverse colour rules in all charts and rankings.

### Loading and refresh behaviour

Initial load should render the structural shell quickly, then populate data from cached/materialised analytics. A visible refresh timestamp must indicate data age. If a user changes geography, period or programme, cancel stale in-flight requests and render one consistent new state rather than mixing old and new values. Background refresh may update the cache, but the current screen should not silently change figures in the middle of an export or AI generation; those actions bind to the active calculation run.

### Error and edge states

- IFA values \>100% are retained and flagged for numerator/denominator definition review.

- Ultrasound, Hb and first-trimester indicators use ANC1 denominator and remain calculable at facility level without population.

### AI behaviour

AI content on this screen must be generated from the screen evidence package, which includes only the authorised calculated outputs, comparisons, contributions and approved quality flags required for the task. AI must not recalculate formulas, invent missing target values or infer individual causes from aggregate data. If AI is disabled or unavailable, deterministic findings such as target status, largest improvement/deterioration and leading contributors should still populate a basic insight panel.

### Export behaviour

Excel, PowerPoint and narrative-report actions must preserve the current geography, period, programme, comparison period and indicator configuration. Exports should use the same calculation-run ID and therefore exactly match the screen values. If an export template cannot accommodate all selected indicators, the system should use a documented overflow/continuation template rather than shrink text until unreadable.

### Acceptance criteria

- No value on this screen differs from the equivalent calculation API response.

- Changing scope never reveals unauthorised units.

- All red/blue cells can be explained through an evidence drawer.

- No-data and stale-data states are explicit and never silently converted to zero.

- The screen remains usable at common laptop resolutions and retains readable tables/charts for projection.

## E.7 Intrapartum and Newborn Workspace

Analyse delivery access, interventions, newborn care and maternal/perinatal outcomes while respecting different indicator directions.

### Scope resolution and data dependencies

The Intrapartum and Newborn Workspace screen resolves the authenticated user first, then the requested geography and period, and only then loads indicator data. The server must confirm that the requested geography is equal to or below the user’s authorised root and that every requested indicator belongs to an authorised programme. Population-based measures resolve the population year from the configured financial-year rule; service-derived measures use source service counts; event-based measures query the relevant MPDSR calculation outputs. The screen should receive a single coherent calculation-run identifier so all cards, tables, charts and export actions represent the same analytical snapshot.

### Required visual components

- Institutional delivery, C-section, KMC and resuscitation scorecard

- PMR, fresh stillbirth and MMR outcomes

- Year comparison

- Mortality trend counts/rates when denominators exist

- Referral/burden context

- Data-quality flags for \>100% bounded measures

### Interaction behaviour

- C-section status is calculated against the desired 5-15% range, so both extremes can be selected as problems.

- Clicking MMR shows maternal deaths count and live-birth denominator.

- PMR drill-down shows components fresh SB, macerated SB and newborn deaths.

### Loading and refresh behaviour

Initial load should render the structural shell quickly, then populate data from cached/materialised analytics. A visible refresh timestamp must indicate data age. If a user changes geography, period or programme, cancel stale in-flight requests and render one consistent new state rather than mixing old and new values. Background refresh may update the cache, but the current screen should not silently change figures in the middle of an export or AI generation; those actions bind to the active calculation run.

### Error and edge states

- Do not convert mortality counts into monthly rates without matching monthly denominators.

- Successful resuscitation \>100% becomes BLUE and is excluded from performance-improvement narrative.

- District MMR with small counts is always displayed with count context.

### AI behaviour

AI content on this screen must be generated from the screen evidence package, which includes only the authorised calculated outputs, comparisons, contributions and approved quality flags required for the task. AI must not recalculate formulas, invent missing target values or infer individual causes from aggregate data. If AI is disabled or unavailable, deterministic findings such as target status, largest improvement/deterioration and leading contributors should still populate a basic insight panel.

### Export behaviour

Excel, PowerPoint and narrative-report actions must preserve the current geography, period, programme, comparison period and indicator configuration. Exports should use the same calculation-run ID and therefore exactly match the screen values. If an export template cannot accommodate all selected indicators, the system should use a documented overflow/continuation template rather than shrink text until unreadable.

### Acceptance criteria

- No value on this screen differs from the equivalent calculation API response.

- Changing scope never reveals unauthorised units.

- All red/blue cells can be explained through an evidence drawer.

- No-data and stale-data states are explicit and never silently converted to zero.

- The screen remains usable at common laptop resolutions and retains readable tables/charts for projection.

## E.8 Immunization and Child Health Workspace

Track vaccine and child-health coverage using configured target-population coefficients and show completion/dropout across dose series.

### Scope resolution and data dependencies

The Immunization and Child Health Workspace screen resolves the authenticated user first, then the requested geography and period, and only then loads indicator data. The server must confirm that the requested geography is equal to or below the user’s authorised root and that every requested indicator belongs to an authorised programme. Population-based measures resolve the population year from the configured financial-year rule; service-derived measures use source service counts; event-based measures query the relevant MPDSR calculation outputs. The screen should receive a single coherent calculation-run identifier so all cards, tables, charts and export actions represent the same analytical snapshot.

### Required visual components

- Antigen scorecard

- Vaccine continuum

- Dropout indicators

- Monthly target-vs-administered chart

- Map

- Low/zero-performing facilities

- Data-quality warnings

### Interaction behaviour

- User selects antigen or series; denominator coefficient and period scaling are shown in methodology.

- MV1-MV4 continuum highlights completion gap.

- Facility ranking can use missed target children in addition to coverage.

### Loading and refresh behaviour

Initial load should render the structural shell quickly, then populate data from cached/materialised analytics. A visible refresh timestamp must indicate data age. If a user changes geography, period or programme, cancel stale in-flight requests and render one consistent new state rather than mixing old and new values. Background refresh may update the cache, but the current screen should not silently change figures in the middle of an export or AI generation; those actions bind to the active calculation run.

### Error and edge states

- Malaria vaccine doses 1-4 use 4.3% annual population target.

- Birth-dose BCG/OPV0/HepB use 4.85%.

- If approved RAG targets are not configured, calculate coverage without invented status.

### AI behaviour

AI content on this screen must be generated from the screen evidence package, which includes only the authorised calculated outputs, comparisons, contributions and approved quality flags required for the task. AI must not recalculate formulas, invent missing target values or infer individual causes from aggregate data. If AI is disabled or unavailable, deterministic findings such as target status, largest improvement/deterioration and leading contributors should still populate a basic insight panel.

### Export behaviour

Excel, PowerPoint and narrative-report actions must preserve the current geography, period, programme, comparison period and indicator configuration. Exports should use the same calculation-run ID and therefore exactly match the screen values. If an export template cannot accommodate all selected indicators, the system should use a documented overflow/continuation template rather than shrink text until unreadable.

### Acceptance criteria

- No value on this screen differs from the equivalent calculation API response.

- Changing scope never reveals unauthorised units.

- All red/blue cells can be explained through an evidence drawer.

- No-data and stale-data states are explicit and never silently converted to zero.

- The screen remains usable at common laptop resolutions and retains readable tables/charts for projection.

## E.9 MPDSR Workspace

Integrate reported deaths with notification and review event workflows for both perinatal and maternal deaths.

### Scope resolution and data dependencies

The MPDSR Workspace screen resolves the authenticated user first, then the requested geography and period, and only then loads indicator data. The server must confirm that the requested geography is equal to or below the user’s authorised root and that every requested indicator belongs to an authorised programme. Population-based measures resolve the population year from the configured financial-year rule; service-derived measures use source service counts; event-based measures query the relevant MPDSR calculation outputs. The screen should receive a single coherent calculation-run identifier so all cards, tables, charts and export actions represent the same analytical snapshot.

### Required visual components

- Combined perinatal/maternal process scorecard

- Quarterly notification/review performance

- Active events not completed

- Cause patterns

- Timeliness

- Reconciliation/data-quality issues

- Learning insights

### Interaction behaviour

- Process table uses neutral count columns and colour-coded percentage columns.

- Active events can be filtered by district/facility for authorised operational users.

- Cause tabs switch perinatal/maternal and apply different privacy aggregation rules.

- Clicking a reconciliation issue opens aggregate evidence; case linkage is shown only if a shared UID exists.

### Loading and refresh behaviour

Initial load should render the structural shell quickly, then populate data from cached/materialised analytics. A visible refresh timestamp must indicate data age. If a user changes geography, period or programme, cancel stale in-flight requests and render one consistent new state rather than mixing old and new values. Background refresh may update the cache, but the current screen should not silently change figures in the middle of an export or AI generation; those actions bind to the active calculation run.

### Error and edge states

- Perinatal target \>=90%; maternal target 100% with distinct colour bands.

- Same/next-day notification is clearly labelled as a proxy where timestamps are unavailable.

- Maternal clinical causes default to regional/national aggregation and never expose identifiable narrative combinations.

### AI behaviour

AI content on this screen must be generated from the screen evidence package, which includes only the authorised calculated outputs, comparisons, contributions and approved quality flags required for the task. AI must not recalculate formulas, invent missing target values or infer individual causes from aggregate data. If AI is disabled or unavailable, deterministic findings such as target status, largest improvement/deterioration and leading contributors should still populate a basic insight panel.

### Export behaviour

Excel, PowerPoint and narrative-report actions must preserve the current geography, period, programme, comparison period and indicator configuration. Exports should use the same calculation-run ID and therefore exactly match the screen values. If an export template cannot accommodate all selected indicators, the system should use a documented overflow/continuation template rather than shrink text until unreadable.

### Acceptance criteria

- No value on this screen differs from the equivalent calculation API response.

- Changing scope never reveals unauthorised units.

- All red/blue cells can be explained through an evidence drawer.

- No-data and stale-data states are explicit and never silently converted to zero.

- The screen remains usable at common laptop resolutions and retains readable tables/charts for projection.

## E.10 Maps Workspace

Provide reusable geographic exploration for any mapped indicator and geography level.

### Scope resolution and data dependencies

The Maps Workspace screen resolves the authenticated user first, then the requested geography and period, and only then loads indicator data. The server must confirm that the requested geography is equal to or below the user’s authorised root and that every requested indicator belongs to an authorised programme. Population-based measures resolve the population year from the configured financial-year rule; service-derived measures use source service counts; event-based measures query the relevant MPDSR calculation outputs. The screen should receive a single coherent calculation-run identifier so all cards, tables, charts and export actions represent the same analytical snapshot.

### Required visual components

- Map canvas

- Indicator selector

- Period selector

- Legend

- Layer selector

- Hover/click tooltips

- Drill-down breadcrumb

- No-data list

### Interaction behaviour

- Clicking polygon drills to child geography where authorised.

- Tooltip shows value, status, numerator/denominator summary and last refresh.

- User may upload/administer GeoJSON only with mapping permission.

### Loading and refresh behaviour

Initial load should render the structural shell quickly, then populate data from cached/materialised analytics. A visible refresh timestamp must indicate data age. If a user changes geography, period or programme, cancel stale in-flight requests and render one consistent new state rather than mixing old and new values. Background refresh may update the cache, but the current screen should not silently change figures in the middle of an export or AI generation; those actions bind to the active calculation run.

### Error and edge states

- No geometry never means no data; unmapped units remain in tables.

- Map colours use indicator-specific RAG, not a universal high/medium/low scale unless explicitly configured.

### AI behaviour

AI content on this screen must be generated from the screen evidence package, which includes only the authorised calculated outputs, comparisons, contributions and approved quality flags required for the task. AI must not recalculate formulas, invent missing target values or infer individual causes from aggregate data. If AI is disabled or unavailable, deterministic findings such as target status, largest improvement/deterioration and leading contributors should still populate a basic insight panel.

### Export behaviour

Excel, PowerPoint and narrative-report actions must preserve the current geography, period, programme, comparison period and indicator configuration. Exports should use the same calculation-run ID and therefore exactly match the screen values. If an export template cannot accommodate all selected indicators, the system should use a documented overflow/continuation template rather than shrink text until unreadable.

### Acceptance criteria

- No value on this screen differs from the equivalent calculation API response.

- Changing scope never reveals unauthorised units.

- All red/blue cells can be explained through an evidence drawer.

- No-data and stale-data states are explicit and never silently converted to zero.

- The screen remains usable at common laptop resolutions and retains readable tables/charts for projection.

## E.11 Trends Workspace

Allow analysts to explore longitudinal performance, compare indicators/geographies and identify unusual changes.

### Scope resolution and data dependencies

The Trends Workspace screen resolves the authenticated user first, then the requested geography and period, and only then loads indicator data. The server must confirm that the requested geography is equal to or below the user’s authorised root and that every requested indicator belongs to an authorised programme. Population-based measures resolve the population year from the configured financial-year rule; service-derived measures use source service counts; event-based measures query the relevant MPDSR calculation outputs. The screen should receive a single coherent calculation-run identifier so all cards, tables, charts and export actions represent the same analytical snapshot.

### Required visual components

- Indicator selector

- Geography comparison selector

- Time granularity

- Trend chart

- Anomaly markers

- Data table

- Export chart/data

### Interaction behaviour

- Monthly, quarterly and financial-year views resolve denominators correctly.

- User can overlay target lines and prior-year series.

- Anomaly marker opens explanation of rule and baseline.

### Loading and refresh behaviour

Initial load should render the structural shell quickly, then populate data from cached/materialised analytics. A visible refresh timestamp must indicate data age. If a user changes geography, period or programme, cancel stale in-flight requests and render one consistent new state rather than mixing old and new values. Background refresh may update the cache, but the current screen should not silently change figures in the middle of an export or AI generation; those actions bind to the active calculation run.

### Error and edge states

- Counts and rates are never mixed on the same axis without explicit dual-axis labelling.

- Missing months appear as gaps, not zeros.

### AI behaviour

AI content on this screen must be generated from the screen evidence package, which includes only the authorised calculated outputs, comparisons, contributions and approved quality flags required for the task. AI must not recalculate formulas, invent missing target values or infer individual causes from aggregate data. If AI is disabled or unavailable, deterministic findings such as target status, largest improvement/deterioration and leading contributors should still populate a basic insight panel.

### Export behaviour

Excel, PowerPoint and narrative-report actions must preserve the current geography, period, programme, comparison period and indicator configuration. Exports should use the same calculation-run ID and therefore exactly match the screen values. If an export template cannot accommodate all selected indicators, the system should use a documented overflow/continuation template rather than shrink text until unreadable.

### Acceptance criteria

- No value on this screen differs from the equivalent calculation API response.

- Changing scope never reveals unauthorised units.

- All red/blue cells can be explained through an evidence drawer.

- No-data and stale-data states are explicit and never silently converted to zero.

- The screen remains usable at common laptop resolutions and retains readable tables/charts for projection.

## E.12 Data Quality Workspace

Turn quality problems into a trackable operational workflow rather than scattered warning icons.

### Scope resolution and data dependencies

The Data Quality Workspace screen resolves the authenticated user first, then the requested geography and period, and only then loads indicator data. The server must confirm that the requested geography is equal to or below the user’s authorised root and that every requested indicator belongs to an authorised programme. Population-based measures resolve the population year from the configured financial-year rule; service-derived measures use source service counts; event-based measures query the relevant MPDSR calculation outputs. The screen should receive a single coherent calculation-run identifier so all cards, tables, charts and export actions represent the same analytical snapshot.

### Required visual components

- Flag table

- Severity filters

- Programme/geography filters

- Rule filters

- Evidence drawer

- Resolution note/status

- Trend of unresolved flags

### Interaction behaviour

- Authorised users can mark a flag reviewed/resolved without deleting the original detection.

- Filtering by facility exposes recurring issue patterns.

- A resolved flag remains auditable with user/time/note.

### Loading and refresh behaviour

Initial load should render the structural shell quickly, then populate data from cached/materialised analytics. A visible refresh timestamp must indicate data age. If a user changes geography, period or programme, cancel stale in-flight requests and render one consistent new state rather than mixing old and new values. Background refresh may update the cache, but the current screen should not silently change figures in the middle of an export or AI generation; those actions bind to the active calculation run.

### Error and edge states

- Performance and data-quality statuses remain separate.

- Automated duplicate detection creates a candidate flag and never deletes records automatically.

### AI behaviour

AI content on this screen must be generated from the screen evidence package, which includes only the authorised calculated outputs, comparisons, contributions and approved quality flags required for the task. AI must not recalculate formulas, invent missing target values or infer individual causes from aggregate data. If AI is disabled or unavailable, deterministic findings such as target status, largest improvement/deterioration and leading contributors should still populate a basic insight panel.

### Export behaviour

Excel, PowerPoint and narrative-report actions must preserve the current geography, period, programme, comparison period and indicator configuration. Exports should use the same calculation-run ID and therefore exactly match the screen values. If an export template cannot accommodate all selected indicators, the system should use a documented overflow/continuation template rather than shrink text until unreadable.

### Acceptance criteria

- No value on this screen differs from the equivalent calculation API response.

- Changing scope never reveals unauthorised units.

- All red/blue cells can be explained through an evidence drawer.

- No-data and stale-data states are explicit and never silently converted to zero.

- The screen remains usable at common laptop resolutions and retains readable tables/charts for projection.

## E.13 AI Insights / Ask the Data

Provide conversational analysis over verified evidence without giving the LLM unrestricted database access.

### Scope resolution and data dependencies

The AI Insights / Ask the Data screen resolves the authenticated user first, then the requested geography and period, and only then loads indicator data. The server must confirm that the requested geography is equal to or below the user’s authorised root and that every requested indicator belongs to an authorised programme. Population-based measures resolve the population year from the configured financial-year rule; service-derived measures use source service counts; event-based measures query the relevant MPDSR calculation outputs. The screen should receive a single coherent calculation-run identifier so all cards, tables, charts and export actions represent the same analytical snapshot.

### Required visual components

- Question input

- Suggested questions

- Answer panel

- Evidence references

- Follow-up actions

- Provider/cost status where appropriate

### Interaction behaviour

- Backend parses question into authorised deterministic query/analytics tasks before LLM explanation.

- User can click evidence references to open the underlying indicator or table.

- Sensitive questions may be refused or reduced to aggregate evidence according to policy.

### Loading and refresh behaviour

Initial load should render the structural shell quickly, then populate data from cached/materialised analytics. A visible refresh timestamp must indicate data age. If a user changes geography, period or programme, cancel stale in-flight requests and render one consistent new state rather than mixing old and new values. Background refresh may update the cache, but the current screen should not silently change figures in the middle of an export or AI generation; those actions bind to the active calculation run.

### Error and edge states

- AI must say when the available evidence cannot answer a causal question.

- No prompt may broaden geography beyond the current user scope.

### AI behaviour

AI content on this screen must be generated from the screen evidence package, which includes only the authorised calculated outputs, comparisons, contributions and approved quality flags required for the task. AI must not recalculate formulas, invent missing target values or infer individual causes from aggregate data. If AI is disabled or unavailable, deterministic findings such as target status, largest improvement/deterioration and leading contributors should still populate a basic insight panel.

### Export behaviour

Excel, PowerPoint and narrative-report actions must preserve the current geography, period, programme, comparison period and indicator configuration. Exports should use the same calculation-run ID and therefore exactly match the screen values. If an export template cannot accommodate all selected indicators, the system should use a documented overflow/continuation template rather than shrink text until unreadable.

### Acceptance criteria

- No value on this screen differs from the equivalent calculation API response.

- Changing scope never reveals unauthorised units.

- All red/blue cells can be explained through an evidence drawer.

- No-data and stale-data states are explicit and never silently converted to zero.

- The screen remains usable at common laptop resolutions and retains readable tables/charts for projection.

## E.14 Reports and Exports

Centralise reproducible publication products generated from approved templates and calculation runs.

### Scope resolution and data dependencies

The Reports and Exports screen resolves the authenticated user first, then the requested geography and period, and only then loads indicator data. The server must confirm that the requested geography is equal to or below the user’s authorised root and that every requested indicator belongs to an authorised programme. Population-based measures resolve the population year from the configured financial-year rule; service-derived measures use source service counts; event-based measures query the relevant MPDSR calculation outputs. The screen should receive a single coherent calculation-run identifier so all cards, tables, charts and export actions represent the same analytical snapshot.

### Required visual components

- Export type selector

- Template selector

- Scope/period summary

- Generation queue/history

- Download links

- Calculation run ID

### Interaction behaviour

- Generating PPTX/Excel/report creates a background job and returns status.

- User can regenerate an old report from stored run inputs if retention policy allows.

### Loading and refresh behaviour

Initial load should render the structural shell quickly, then populate data from cached/materialised analytics. A visible refresh timestamp must indicate data age. If a user changes geography, period or programme, cancel stale in-flight requests and render one consistent new state rather than mixing old and new values. Background refresh may update the cache, but the current screen should not silently change figures in the middle of an export or AI generation; those actions bind to the active calculation run.

### Error and edge states

- Exports inherit permissions at generation time.

- Sensitive event-level exports require explicit additional permission.

### AI behaviour

AI content on this screen must be generated from the screen evidence package, which includes only the authorised calculated outputs, comparisons, contributions and approved quality flags required for the task. AI must not recalculate formulas, invent missing target values or infer individual causes from aggregate data. If AI is disabled or unavailable, deterministic findings such as target status, largest improvement/deterioration and leading contributors should still populate a basic insight panel.

### Export behaviour

Excel, PowerPoint and narrative-report actions must preserve the current geography, period, programme, comparison period and indicator configuration. Exports should use the same calculation-run ID and therefore exactly match the screen values. If an export template cannot accommodate all selected indicators, the system should use a documented overflow/continuation template rather than shrink text until unreadable.

### Acceptance criteria

- No value on this screen differs from the equivalent calculation API response.

- Changing scope never reveals unauthorised units.

- All red/blue cells can be explained through an evidence drawer.

- No-data and stale-data states are explicit and never silently converted to zero.

- The screen remains usable at common laptop resolutions and retains readable tables/charts for projection.

## E.15 Administration

Manage configuration that should change without code deployment while preserving auditability.

### Scope resolution and data dependencies

The Administration screen resolves the authenticated user first, then the requested geography and period, and only then loads indicator data. The server must confirm that the requested geography is equal to or below the user’s authorised root and that every requested indicator belongs to an authorised programme. Population-based measures resolve the population year from the configured financial-year rule; service-derived measures use source service counts; event-based measures query the relevant MPDSR calculation outputs. The screen should receive a single coherent calculation-run identifier so all cards, tables, charts and export actions represent the same analytical snapshot.

### Required visual components

- Users/roles

- Org-unit mappings

- Population versions

- Indicator registry/versions

- DHIS2 mappings

- GeoJSON

- AI providers

- Export templates

- Audit log

- System health

### Interaction behaviour

- Every material change is versioned/audited.

- Publishing a new indicator version requires effective period and validation.

- Template previews are available before activation.

### Loading and refresh behaviour

Initial load should render the structural shell quickly, then populate data from cached/materialised analytics. A visible refresh timestamp must indicate data age. If a user changes geography, period or programme, cancel stale in-flight requests and render one consistent new state rather than mixing old and new values. Background refresh may update the cache, but the current screen should not silently change figures in the middle of an export or AI generation; those actions bind to the active calculation run.

### Error and edge states

- Admins cannot edit historical calculation records to hide prior values.

- Secrets are referenced securely and never displayed after save.

### AI behaviour

AI content on this screen must be generated from the screen evidence package, which includes only the authorised calculated outputs, comparisons, contributions and approved quality flags required for the task. AI must not recalculate formulas, invent missing target values or infer individual causes from aggregate data. If AI is disabled or unavailable, deterministic findings such as target status, largest improvement/deterioration and leading contributors should still populate a basic insight panel.

### Export behaviour

Excel, PowerPoint and narrative-report actions must preserve the current geography, period, programme, comparison period and indicator configuration. Exports should use the same calculation-run ID and therefore exactly match the screen values. If an export template cannot accommodate all selected indicators, the system should use a documented overflow/continuation template rather than shrink text until unreadable.

### Acceptance criteria

- No value on this screen differs from the equivalent calculation API response.

- Changing scope never reveals unauthorised units.

- All red/blue cells can be explained through an evidence drawer.

- No-data and stale-data states are explicit and never silently converted to zero.

- The screen remains usable at common laptop resolutions and retains readable tables/charts for projection.

# Appendix F. Detailed Specifications for the 26 Implementation Prompts

The twenty-six prompts should be written later as executable implementation instructions of roughly 1,300-1,500 words each. This appendix gives the IDE context that each prompt must contain so implementation can begin without repeatedly rediscovering product intent. These are not substitutes for the final prompts; they are detailed prompt contracts and acceptance boundaries.

## F.1 Prompt 1: Master Application Architecture

Objective: Create the repository/service architecture, environment conventions, frontend/backend boundaries, configuration strategy, testing harness, logging and coding standards.

### Context the prompt must restate

The prompt must remind the IDE that this is one increment in a national, role-based health performance platform whose initial release is MNCH. It must reference the existing repository and the relevant preceding phases, insist on deterministic calculation and server-side authorisation, and explicitly preserve previously approved regression behaviour. The IDE should inspect existing code before adding new abstractions so that each phase extends rather than replaces working foundations.

### Required deliverables

- Working development environment; health endpoints; CI-ready test scaffold; documented folder structure.

- Automated tests for normal, missing-data and permission/error states.

- Developer documentation that explains configuration or migrations added by the prompt.

- Short handoff noting changed files, tests run, unresolved decisions and next-phase dependencies.

### Implementation depth expected

This prompt should not stop at interface stubs. For Master Application Architecture, the implementation must include domain/service logic, API or UI integration as appropriate, persistence where required, validation, typed/structured request and response contracts, error handling, audit/logging hooks, and test coverage. Mock data may be used only in automated tests or isolated development fixtures; production screens and services should be wired to the real internal interfaces created in earlier phases.

### Guardrails

- Do not implement programme formulas yet.

- Keep AI provider-independent.

- Choose interfaces that support national scale and background jobs.

- Do not silently modify already approved indicator targets or formulas.

- Do not remove auditability to simplify implementation.

- Do not return a “done” status if acceptance tests are failing.

### Acceptance evidence

The final IDE response for this prompt should include the exact tests executed and their result, important API/UI examples, any migration or environment variable introduced, and a concise verification checklist. Where the prompt creates a visible screen, provide screenshots or render verification. Where it creates a calculation/data service, provide sample deterministic input/output demonstrating the contract.

## F.2 Prompt 2: Database and Domain Model

Objective: Implement PostgreSQL/PostGIS schema for users, permissions, geography, populations, programmes, indicators, versions, source mappings, raw data, calculation runs, quality flags, exports, AI requests and audit log.

### Context the prompt must restate

The prompt must remind the IDE that this is one increment in a national, role-based health performance platform whose initial release is MNCH. It must reference the existing repository and the relevant preceding phases, insist on deterministic calculation and server-side authorisation, and explicitly preserve previously approved regression behaviour. The IDE should inspect existing code before adding new abstractions so that each phase extends rather than replaces working foundations.

### Required deliverables

- Migrations, ERD/domain documentation, seed data for core enumerations and tests.

- Automated tests for normal, missing-data and permission/error states.

- Developer documentation that explains configuration or migrations added by the prompt.

- Short handoff noting changed files, tests run, unresolved decisions and next-phase dependencies.

### Implementation depth expected

This prompt should not stop at interface stubs. For Database and Domain Model, the implementation must include domain/service logic, API or UI integration as appropriate, persistence where required, validation, typed/structured request and response contracts, error handling, audit/logging hooks, and test coverage. Mock data may be used only in automated tests or isolated development fixtures; production screens and services should be wired to the real internal interfaces created in earlier phases.

### Guardrails

- Historical versions must be immutable by default.

- Geometry and organisation hierarchy must support validity dates.

- Do not silently modify already approved indicator targets or formulas.

- Do not remove auditability to simplify implementation.

- Do not return a “done” status if acceptance tests are failing.

### Acceptance evidence

The final IDE response for this prompt should include the exact tests executed and their result, important API/UI examples, any migration or environment variable introduced, and a concise verification checklist. Where the prompt creates a visible screen, provide screenshots or render verification. Where it creates a calculation/data service, provide sample deterministic input/output demonstrating the contract.

## F.3 Prompt 3: Authentication and Authorisation

Objective: Implement identity/session approach and three-dimensional geography/programme/action authorisation with scope-aware landing context.

### Context the prompt must restate

The prompt must remind the IDE that this is one increment in a national, role-based health performance platform whose initial release is MNCH. It must reference the existing repository and the relevant preceding phases, insist on deterministic calculation and server-side authorisation, and explicitly preserve previously approved regression behaviour. The IDE should inspect existing code before adding new abstractions so that each phase extends rather than replaces working foundations.

### Required deliverables

- Login/session flow, /me/context, permission middleware, role fixtures and boundary tests.

- Automated tests for normal, missing-data and permission/error states.

- Developer documentation that explains configuration or migrations added by the prompt.

- Short handoff noting changed files, tests run, unresolved decisions and next-phase dependencies.

### Implementation depth expected

This prompt should not stop at interface stubs. For Authentication and Authorisation, the implementation must include domain/service logic, API or UI integration as appropriate, persistence where required, validation, typed/structured request and response contracts, error handling, audit/logging hooks, and test coverage. Mock data may be used only in automated tests or isolated development fixtures; production screens and services should be wired to the real internal interfaces created in earlier phases.

### Guardrails

- Server-side checks on every data/export/AI endpoint.

- URL manipulation must not expand access.

- Do not silently modify already approved indicator targets or formulas.

- Do not remove auditability to simplify implementation.

- Do not return a “done” status if acceptance tests are failing.

### Acceptance evidence

The final IDE response for this prompt should include the exact tests executed and their result, important API/UI examples, any migration or environment variable introduced, and a concise verification checklist. Where the prompt creates a visible screen, provide screenshots or render verification. Where it creates a calculation/data service, provide sample deterministic input/output demonstrating the contract.

## F.4 Prompt 4: DHIS2 Aggregate Connector

Objective: Implement metadata-driven retrieval of aggregate HMIS data from DHIS2 Analytics API with caching, retries, periods and org-unit descendants.

### Context the prompt must restate

The prompt must remind the IDE that this is one increment in a national, role-based health performance platform whose initial release is MNCH. It must reference the existing repository and the relevant preceding phases, insist on deterministic calculation and server-side authorisation, and explicitly preserve previously approved regression behaviour. The IDE should inspect existing code before adding new abstractions so that each phase extends rather than replaces working foundations.

### Required deliverables

- Connector service, mapping layer, raw-normalised storage, sync logs and mocked integration tests.

- Automated tests for normal, missing-data and permission/error states.

- Developer documentation that explains configuration or migrations added by the prompt.

- Short handoff noting changed files, tests run, unresolved decisions and next-phase dependencies.

### Implementation depth expected

This prompt should not stop at interface stubs. For DHIS2 Aggregate Connector, the implementation must include domain/service logic, API or UI integration as appropriate, persistence where required, validation, typed/structured request and response contracts, error handling, audit/logging hooks, and test coverage. Mock data may be used only in automated tests or isolated development fixtures; production screens and services should be wired to the real internal interfaces created in earlier phases.

### Guardrails

- Never hard-code data-element UIDs in calculations.

- Missing upstream data are null/missing, not zero.

- Do not silently modify already approved indicator targets or formulas.

- Do not remove auditability to simplify implementation.

- Do not return a “done” status if acceptance tests are failing.

### Acceptance evidence

The final IDE response for this prompt should include the exact tests executed and their result, important API/UI examples, any migration or environment variable introduced, and a concise verification checklist. Where the prompt creates a visible screen, provide screenshots or render verification. Where it creates a calculation/data service, provide sample deterministic input/output demonstrating the contract.

## F.5 Prompt 5: DHIS2 Event and Tracker Connector

Objective: Implement Event Analytics query/aggregate and Tracker Events retrieval for event programmes, including status and mapped dataValues.

### Context the prompt must restate

The prompt must remind the IDE that this is one increment in a national, role-based health performance platform whose initial release is MNCH. It must reference the existing repository and the relevant preceding phases, insist on deterministic calculation and server-side authorisation, and explicitly preserve previously approved regression behaviour. The IDE should inspect existing code before adding new abstractions so that each phase extends rather than replaces working foundations.

### Required deliverables

- Event connector, semantic mapping, current-event retrieval, paging/compression handling and tests.

- Automated tests for normal, missing-data and permission/error states.

- Developer documentation that explains configuration or migrations added by the prompt.

- Short handoff noting changed files, tests run, unresolved decisions and next-phase dependencies.

### Implementation depth expected

This prompt should not stop at interface stubs. For DHIS2 Event and Tracker Connector, the implementation must include domain/service logic, API or UI integration as appropriate, persistence where required, validation, typed/structured request and response contracts, error handling, audit/logging hooks, and test coverage. Mock data may be used only in automated tests or isolated development fixtures; production screens and services should be wired to the real internal interfaces created in earlier phases.

### Guardrails

- Preserve ACTIVE vs COMPLETED.

- Store only approved sensitive fields.

- Do not silently modify already approved indicator targets or formulas.

- Do not remove auditability to simplify implementation.

- Do not return a “done” status if acceptance tests are failing.

### Acceptance evidence

The final IDE response for this prompt should include the exact tests executed and their result, important API/UI examples, any migration or environment variable introduced, and a concise verification checklist. Where the prompt creates a visible screen, provide screenshots or render verification. Where it creates a calculation/data service, provide sample deterministic input/output demonstrating the contract.

## F.6 Prompt 6: National Geography and Population Engine

Objective: Import national hierarchy/populations, map DHIS2 UIDs, support regions/sub-regions/district/city/sub-county/facility and facility population overrides.

### Context the prompt must restate

The prompt must remind the IDE that this is one increment in a national, role-based health performance platform whose initial release is MNCH. It must reference the existing repository and the relevant preceding phases, insist on deterministic calculation and server-side authorisation, and explicitly preserve previously approved regression behaviour. The IDE should inspect existing code before adding new abstractions so that each phase extends rather than replaces working foundations.

### Required deliverables

- Population resolution API, imports, versioning, approval/audit and test fixtures.

- Automated tests for normal, missing-data and permission/error states.

- Developer documentation that explains configuration or migrations added by the prompt.

- Short handoff noting changed files, tests run, unresolved decisions and next-phase dependencies.

### Implementation depth expected

This prompt should not stop at interface stubs. For National Geography and Population Engine, the implementation must include domain/service logic, API or UI integration as appropriate, persistence where required, validation, typed/structured request and response contracts, error handling, audit/logging hooks, and test coverage. Mock data may be used only in automated tests or isolated development fixtures; production screens and services should be wired to the real internal interfaces created in earlier phases.

### Guardrails

- FY-to-population-year mapping is configurable.

- Facility overrides do not rewrite official parent totals.

- Do not silently modify already approved indicator targets or formulas.

- Do not remove auditability to simplify implementation.

- Do not return a “done” status if acceptance tests are failing.

### Acceptance evidence

The final IDE response for this prompt should include the exact tests executed and their result, important API/UI examples, any migration or environment variable introduced, and a concise verification checklist. Where the prompt creates a visible screen, provide screenshots or render verification. Where it creates a calculation/data service, provide sample deterministic input/output demonstrating the contract.

## F.7 Prompt 7: Indicator Calculation Engine

Objective: Implement registry-driven formula evaluation, denominator types, period scaling, aggregation, precision and status classification.

### Context the prompt must restate

The prompt must remind the IDE that this is one increment in a national, role-based health performance platform whose initial release is MNCH. It must reference the existing repository and the relevant preceding phases, insist on deterministic calculation and server-side authorisation, and explicitly preserve previously approved regression behaviour. The IDE should inspect existing code before adding new abstractions so that each phase extends rather than replaces working foundations.

### Required deliverables

- Calculation service, versioned registry schema, evidence output and regression tests.

- Automated tests for normal, missing-data and permission/error states.

- Developer documentation that explains configuration or migrations added by the prompt.

- Short handoff noting changed files, tests run, unresolved decisions and next-phase dependencies.

### Implementation depth expected

This prompt should not stop at interface stubs. For Indicator Calculation Engine, the implementation must include domain/service logic, API or UI integration as appropriate, persistence where required, validation, typed/structured request and response contracts, error handling, audit/logging hooks, and test coverage. Mock data may be used only in automated tests or isolated development fixtures; production screens and services should be wired to the real internal interfaces created in earlier phases.

### Guardrails

- Aggregate numerators/denominators before calculating parent values.

- BLUE is separate from performance.

- Do not silently modify already approved indicator targets or formulas.

- Do not remove auditability to simplify implementation.

- Do not return a “done” status if acceptance tests are failing.

### Acceptance evidence

The final IDE response for this prompt should include the exact tests executed and their result, important API/UI examples, any migration or environment variable introduced, and a concise verification checklist. Where the prompt creates a visible screen, provide screenshots or render verification. Where it creates a calculation/data service, provide sample deterministic input/output demonstrating the contract.

## F.8 Prompt 8: Data Quality Engine

Objective: Implement rule framework and first rules for \>100 bounded values, mismatches, impossible dates, ACTIVE events, missing denominators, stale reporting and cause completeness.

### Context the prompt must restate

The prompt must remind the IDE that this is one increment in a national, role-based health performance platform whose initial release is MNCH. It must reference the existing repository and the relevant preceding phases, insist on deterministic calculation and server-side authorisation, and explicitly preserve previously approved regression behaviour. The IDE should inspect existing code before adding new abstractions so that each phase extends rather than replaces working foundations.

### Required deliverables

- Quality-rule registry, flags, severities, evidence and resolution workflow API.

- Automated tests for normal, missing-data and permission/error states.

- Developer documentation that explains configuration or migrations added by the prompt.

- Short handoff noting changed files, tests run, unresolved decisions and next-phase dependencies.

### Implementation depth expected

This prompt should not stop at interface stubs. For Data Quality Engine, the implementation must include domain/service logic, API or UI integration as appropriate, persistence where required, validation, typed/structured request and response contracts, error handling, audit/logging hooks, and test coverage. Mock data may be used only in automated tests or isolated development fixtures; production screens and services should be wired to the real internal interfaces created in earlier phases.

### Guardrails

- Do not delete/correct source records automatically.

- Quality state can coexist with performance value.

- Do not silently modify already approved indicator targets or formulas.

- Do not remove auditability to simplify implementation.

- Do not return a “done” status if acceptance tests are failing.

### Acceptance evidence

The final IDE response for this prompt should include the exact tests executed and their result, important API/UI examples, any migration or environment variable introduced, and a concise verification checklist. Where the prompt creates a visible screen, provide screenshots or render verification. Where it creates a calculation/data service, provide sample deterministic input/output demonstrating the contract.

## F.9 Prompt 9: ANC Module

Objective: Configure and build the complete ANC analytics module using agreed formulas, thresholds, maps, trends, continuum and comparison.

### Context the prompt must restate

The prompt must remind the IDE that this is one increment in a national, role-based health performance platform whose initial release is MNCH. It must reference the existing repository and the relevant preceding phases, insist on deterministic calculation and server-side authorisation, and explicitly preserve previously approved regression behaviour. The IDE should inspect existing code before adding new abstractions so that each phase extends rather than replaces working foundations.

### Required deliverables

- ANC APIs/views/tests and export-ready evidence.

- Automated tests for normal, missing-data and permission/error states.

- Developer documentation that explains configuration or migrations added by the prompt.

- Short handoff noting changed files, tests run, unresolved decisions and next-phase dependencies.

### Implementation depth expected

This prompt should not stop at interface stubs. For ANC Module, the implementation must include domain/service logic, API or UI integration as appropriate, persistence where required, validation, typed/structured request and response contracts, error handling, audit/logging hooks, and test coverage. Mock data may be used only in automated tests or isolated development fixtures; production screens and services should be wired to the real internal interfaces created in earlier phases.

### Guardrails

- IFA \>100 retained/flagged.

- Teenage pregnancy inverse.

- Do not silently modify already approved indicator targets or formulas.

- Do not remove auditability to simplify implementation.

- Do not return a “done” status if acceptance tests are failing.

### Acceptance evidence

The final IDE response for this prompt should include the exact tests executed and their result, important API/UI examples, any migration or environment variable introduced, and a concise verification checklist. Where the prompt creates a visible screen, provide screenshots or render verification. Where it creates a calculation/data service, provide sample deterministic input/output demonstrating the contract.

## F.10 Prompt 10: Intrapartum and Newborn Module

Objective: Configure delivery, C-section, KMC, resuscitation, PMR, fresh stillbirth and MMR with correct units/directions.

### Context the prompt must restate

The prompt must remind the IDE that this is one increment in a national, role-based health performance platform whose initial release is MNCH. It must reference the existing repository and the relevant preceding phases, insist on deterministic calculation and server-side authorisation, and explicitly preserve previously approved regression behaviour. The IDE should inspect existing code before adding new abstractions so that each phase extends rather than replaces working foundations.

### Required deliverables

- Module analytics, year comparison, outcome evidence and tests.

- Automated tests for normal, missing-data and permission/error states.

- Developer documentation that explains configuration or migrations added by the prompt.

- Short handoff noting changed files, tests run, unresolved decisions and next-phase dependencies.

### Implementation depth expected

This prompt should not stop at interface stubs. For Intrapartum and Newborn Module, the implementation must include domain/service logic, API or UI integration as appropriate, persistence where required, validation, typed/structured request and response contracts, error handling, audit/logging hooks, and test coverage. Mock data may be used only in automated tests or isolated development fixtures; production screens and services should be wired to the real internal interfaces created in earlier phases.

### Guardrails

- C-section desired range.

- Do not fabricate monthly mortality rates without denominators.

- Do not silently modify already approved indicator targets or formulas.

- Do not remove auditability to simplify implementation.

- Do not return a “done” status if acceptance tests are failing.

### Acceptance evidence

The final IDE response for this prompt should include the exact tests executed and their result, important API/UI examples, any migration or environment variable introduced, and a concise verification checklist. Where the prompt creates a visible screen, provide screenshots or render verification. Where it creates a calculation/data service, provide sample deterministic input/output demonstrating the contract.

## F.11 Prompt 11: Immunization and Child Health Module

Objective: Configure antigen coefficients, period-adjusted targets, coverage, dropout, MV1-MV4 continuum and child-health target groups.

### Context the prompt must restate

The prompt must remind the IDE that this is one increment in a national, role-based health performance platform whose initial release is MNCH. It must reference the existing repository and the relevant preceding phases, insist on deterministic calculation and server-side authorisation, and explicitly preserve previously approved regression behaviour. The IDE should inspect existing code before adding new abstractions so that each phase extends rather than replaces working foundations.

### Required deliverables

- EPI scorecard/trends/continuum logic and tests.

- Automated tests for normal, missing-data and permission/error states.

- Developer documentation that explains configuration or migrations added by the prompt.

- Short handoff noting changed files, tests run, unresolved decisions and next-phase dependencies.

### Implementation depth expected

This prompt should not stop at interface stubs. For Immunization and Child Health Module, the implementation must include domain/service logic, API or UI integration as appropriate, persistence where required, validation, typed/structured request and response contracts, error handling, audit/logging hooks, and test coverage. Mock data may be used only in automated tests or isolated development fixtures; production screens and services should be wired to the real internal interfaces created in earlier phases.

### Guardrails

- MV4 coefficient 4.3%.

- Do not invent unapproved RAG thresholds.

- Do not silently modify already approved indicator targets or formulas.

- Do not remove auditability to simplify implementation.

- Do not return a “done” status if acceptance tests are failing.

### Acceptance evidence

The final IDE response for this prompt should include the exact tests executed and their result, important API/UI examples, any migration or environment variable introduced, and a concise verification checklist. Where the prompt creates a visible screen, provide screenshots or render verification. Where it creates a calculation/data service, provide sample deterministic input/output demonstrating the contract.

## F.12 Prompt 12: MPDSR Module

Objective: Combine aggregate reported deaths with notification/review event data; implement process scorecard, timeliness, active events, causes and reconciliation.

### Context the prompt must restate

The prompt must remind the IDE that this is one increment in a national, role-based health performance platform whose initial release is MNCH. It must reference the existing repository and the relevant preceding phases, insist on deterministic calculation and server-side authorisation, and explicitly preserve previously approved regression behaviour. The IDE should inspect existing code before adding new abstractions so that each phase extends rather than replaces working foundations.

### Required deliverables

- Perinatal/maternal process analytics and privacy-aware cause summaries.

- Automated tests for normal, missing-data and permission/error states.

- Developer documentation that explains configuration or migrations added by the prompt.

- Short handoff noting changed files, tests run, unresolved decisions and next-phase dependencies.

### Implementation depth expected

This prompt should not stop at interface stubs. For MPDSR Module, the implementation must include domain/service logic, API or UI integration as appropriate, persistence where required, validation, typed/structured request and response contracts, error handling, audit/logging hooks, and test coverage. Mock data may be used only in automated tests or isolated development fixtures; production screens and services should be wired to the real internal interfaces created in earlier phases.

### Guardrails

- Perinatal target \>=90; maternal target 100.

- No case-level cascade without shared UID.

- Do not silently modify already approved indicator targets or formulas.

- Do not remove auditability to simplify implementation.

- Do not return a “done” status if acceptance tests are failing.

### Acceptance evidence

The final IDE response for this prompt should include the exact tests executed and their result, important API/UI examples, any migration or environment variable introduced, and a concise verification checklist. Where the prompt creates a visible screen, provide screenshots or render verification. Where it creates a calculation/data service, provide sample deterministic input/output demonstrating the contract.

## F.13 Prompt 13: Global UI Design System

Objective: Implement approved blue/navy DHIS2-like visual system, components, spacing, RAG/BLUE colours and subtle natural background treatment.

### Context the prompt must restate

The prompt must remind the IDE that this is one increment in a national, role-based health performance platform whose initial release is MNCH. It must reference the existing repository and the relevant preceding phases, insist on deterministic calculation and server-side authorisation, and explicitly preserve previously approved regression behaviour. The IDE should inspect existing code before adding new abstractions so that each phase extends rather than replaces working foundations.

### Required deliverables

- Reusable component library, typography, tokens and reference page.

- Automated tests for normal, missing-data and permission/error states.

- Developer documentation that explains configuration or migrations added by the prompt.

- Short handoff noting changed files, tests run, unresolved decisions and next-phase dependencies.

### Implementation depth expected

This prompt should not stop at interface stubs. For Global UI Design System, the implementation must include domain/service logic, API or UI integration as appropriate, persistence where required, validation, typed/structured request and response contracts, error handling, audit/logging hooks, and test coverage. Mock data may be used only in automated tests or isolated development fixtures; production screens and services should be wired to the real internal interfaces created in earlier phases.

### Guardrails

- Preserve original dashboard formatting.

- Natural elements must be subtle, never green-heavy or scenic.

- Do not silently modify already approved indicator targets or formulas.

- Do not remove auditability to simplify implementation.

- Do not return a “done” status if acceptance tests are failing.

### Acceptance evidence

The final IDE response for this prompt should include the exact tests executed and their result, important API/UI examples, any migration or environment variable introduced, and a concise verification checklist. Where the prompt creates a visible screen, provide screenshots or render verification. Where it creates a calculation/data service, provide sample deterministic input/output demonstrating the contract.

## F.14 Prompt 14: National Dashboard

Objective: Build national overview with KPI cards, regional map, scorecard, insights, trends and exports.

### Context the prompt must restate

The prompt must remind the IDE that this is one increment in a national, role-based health performance platform whose initial release is MNCH. It must reference the existing repository and the relevant preceding phases, insist on deterministic calculation and server-side authorisation, and explicitly preserve previously approved regression behaviour. The IDE should inspect existing code before adding new abstractions so that each phase extends rather than replaces working foundations.

### Required deliverables

- Functional national screen wired to real APIs and authorisation.

- Automated tests for normal, missing-data and permission/error states.

- Developer documentation that explains configuration or migrations added by the prompt.

- Short handoff noting changed files, tests run, unresolved decisions and next-phase dependencies.

### Implementation depth expected

This prompt should not stop at interface stubs. For National Dashboard, the implementation must include domain/service logic, API or UI integration as appropriate, persistence where required, validation, typed/structured request and response contracts, error handling, audit/logging hooks, and test coverage. Mock data may be used only in automated tests or isolated development fixtures; production screens and services should be wired to the real internal interfaces created in earlier phases.

### Guardrails

- National user only when authorised.

- Map click drills to region.

- Do not silently modify already approved indicator targets or formulas.

- Do not remove auditability to simplify implementation.

- Do not return a “done” status if acceptance tests are failing.

### Acceptance evidence

The final IDE response for this prompt should include the exact tests executed and their result, important API/UI examples, any migration or environment variable introduced, and a concise verification checklist. Where the prompt creates a visible screen, provide screenshots or render verification. Where it creates a calculation/data service, provide sample deterministic input/output demonstrating the contract.

## F.15 Prompt 15: Regional Dashboard

Objective: Build regional/sub-regional view with district map, district scorecard, insights, trends and priorities.

### Context the prompt must restate

The prompt must remind the IDE that this is one increment in a national, role-based health performance platform whose initial release is MNCH. It must reference the existing repository and the relevant preceding phases, insist on deterministic calculation and server-side authorisation, and explicitly preserve previously approved regression behaviour. The IDE should inspect existing code before adding new abstractions so that each phase extends rather than replaces working foundations.

### Required deliverables

- Reusable scope-aware regional page.

- Automated tests for normal, missing-data and permission/error states.

- Developer documentation that explains configuration or migrations added by the prompt.

- Short handoff noting changed files, tests run, unresolved decisions and next-phase dependencies.

### Implementation depth expected

This prompt should not stop at interface stubs. For Regional Dashboard, the implementation must include domain/service logic, API or UI integration as appropriate, persistence where required, validation, typed/structured request and response contracts, error handling, audit/logging hooks, and test coverage. Mock data may be used only in automated tests or isolated development fixtures; production screens and services should be wired to the real internal interfaces created in earlier phases.

### Guardrails

- Aggregate correctly from child data.

- District/city peers supported.

- Do not silently modify already approved indicator targets or formulas.

- Do not remove auditability to simplify implementation.

- Do not return a “done” status if acceptance tests are failing.

### Acceptance evidence

The final IDE response for this prompt should include the exact tests executed and their result, important API/UI examples, any migration or environment variable introduced, and a concise verification checklist. Where the prompt creates a visible screen, provide screenshots or render verification. Where it creates a calculation/data service, provide sample deterministic input/output demonstrating the contract.

## F.16 Prompt 16: District Facility Performance Dashboard

Objective: Build district screen comparing facilities using table, insights, trends and top/bottom analysis.

### Context the prompt must restate

The prompt must remind the IDE that this is one increment in a national, role-based health performance platform whose initial release is MNCH. It must reference the existing repository and the relevant preceding phases, insist on deterministic calculation and server-side authorisation, and explicitly preserve previously approved regression behaviour. The IDE should inspect existing code before adding new abstractions so that each phase extends rather than replaces working foundations.

### Required deliverables

- Facility comparison screen matching approved mock-up.

- Automated tests for normal, missing-data and permission/error states.

- Developer documentation that explains configuration or migrations added by the prompt.

- Short handoff noting changed files, tests run, unresolved decisions and next-phase dependencies.

### Implementation depth expected

This prompt should not stop at interface stubs. For District Facility Performance Dashboard, the implementation must include domain/service logic, API or UI integration as appropriate, persistence where required, validation, typed/structured request and response contracts, error handling, audit/logging hooks, and test coverage. Mock data may be used only in automated tests or isolated development fixtures; production screens and services should be wired to the real internal interfaces created in earlier phases.

### Guardrails

- Missing facility population affects only relevant indicators.

- BLUE values excluded from default performance ranking.

- Do not silently modify already approved indicator targets or formulas.

- Do not remove auditability to simplify implementation.

- Do not return a “done” status if acceptance tests are failing.

### Acceptance evidence

The final IDE response for this prompt should include the exact tests executed and their result, important API/UI examples, any migration or environment variable introduced, and a concise verification checklist. Where the prompt creates a visible screen, provide screenshots or render verification. Where it creates a calculation/data service, provide sample deterministic input/output demonstrating the contract.

## F.17 Prompt 17: Individual Facility Dashboard

Objective: Build facility profile, catchment population workflow, scorecard, trends, quality alerts and exports.

### Context the prompt must restate

The prompt must remind the IDE that this is one increment in a national, role-based health performance platform whose initial release is MNCH. It must reference the existing repository and the relevant preceding phases, insist on deterministic calculation and server-side authorisation, and explicitly preserve previously approved regression behaviour. The IDE should inspect existing code before adding new abstractions so that each phase extends rather than replaces working foundations.

### Required deliverables

- Facility page and population edit workflow.

- Automated tests for normal, missing-data and permission/error states.

- Developer documentation that explains configuration or migrations added by the prompt.

- Short handoff noting changed files, tests run, unresolved decisions and next-phase dependencies.

### Implementation depth expected

This prompt should not stop at interface stubs. For Individual Facility Dashboard, the implementation must include domain/service logic, API or UI integration as appropriate, persistence where required, validation, typed/structured request and response contracts, error handling, audit/logging hooks, and test coverage. Mock data may be used only in automated tests or isolated development fixtures; production screens and services should be wired to the real internal interfaces created in earlier phases.

### Guardrails

- Audit facility population changes.

- No unnecessary population prompt for service-derived measures.

- Do not silently modify already approved indicator targets or formulas.

- Do not remove auditability to simplify implementation.

- Do not return a “done” status if acceptance tests are failing.

### Acceptance evidence

The final IDE response for this prompt should include the exact tests executed and their result, important API/UI examples, any migration or environment variable introduced, and a concise verification checklist. Where the prompt creates a visible screen, provide screenshots or render verification. Where it creates a calculation/data service, provide sample deterministic input/output demonstrating the contract.

## F.18 Prompt 18: Maps and Geographic Intelligence

Objective: Build reusable map workspace and drill-down with PostGIS/GeoJSON, legends, tooltips and no-geometry handling.

### Context the prompt must restate

The prompt must remind the IDE that this is one increment in a national, role-based health performance platform whose initial release is MNCH. It must reference the existing repository and the relevant preceding phases, insist on deterministic calculation and server-side authorisation, and explicitly preserve previously approved regression behaviour. The IDE should inspect existing code before adding new abstractions so that each phase extends rather than replaces working foundations.

### Required deliverables

- Map components and APIs across levels.

- Automated tests for normal, missing-data and permission/error states.

- Developer documentation that explains configuration or migrations added by the prompt.

- Short handoff noting changed files, tests run, unresolved decisions and next-phase dependencies.

### Implementation depth expected

This prompt should not stop at interface stubs. For Maps and Geographic Intelligence, the implementation must include domain/service logic, API or UI integration as appropriate, persistence where required, validation, typed/structured request and response contracts, error handling, audit/logging hooks, and test coverage. Mock data may be used only in automated tests or isolated development fixtures; production screens and services should be wired to the real internal interfaces created in earlier phases.

### Guardrails

- Map status derives from indicator rules.

- Unmapped units remain visible elsewhere.

- Do not silently modify already approved indicator targets or formulas.

- Do not remove auditability to simplify implementation.

- Do not return a “done” status if acceptance tests are failing.

### Acceptance evidence

The final IDE response for this prompt should include the exact tests executed and their result, important API/UI examples, any migration or environment variable introduced, and a concise verification checklist. Where the prompt creates a visible screen, provide screenshots or render verification. Where it creates a calculation/data service, provide sample deterministic input/output demonstrating the contract.

## F.19 Prompt 19: AI Gateway

Objective: Build provider abstraction, routing, cost/usage logging, privacy policy enforcement, fallback and no-AI mode.

### Context the prompt must restate

The prompt must remind the IDE that this is one increment in a national, role-based health performance platform whose initial release is MNCH. It must reference the existing repository and the relevant preceding phases, insist on deterministic calculation and server-side authorisation, and explicitly preserve previously approved regression behaviour. The IDE should inspect existing code before adding new abstractions so that each phase extends rather than replaces working foundations.

### Required deliverables

- AI service interface and provider adapters.

- Automated tests for normal, missing-data and permission/error states.

- Developer documentation that explains configuration or migrations added by the prompt.

- Short handoff noting changed files, tests run, unresolved decisions and next-phase dependencies.

### Implementation depth expected

This prompt should not stop at interface stubs. For AI Gateway, the implementation must include domain/service logic, API or UI integration as appropriate, persistence where required, validation, typed/structured request and response contracts, error handling, audit/logging hooks, and test coverage. Mock data may be used only in automated tests or isolated development fixtures; production screens and services should be wired to the real internal interfaces created in earlier phases.

### Guardrails

- No raw sensitive MPDSR to external providers by default.

- Core platform remains functional when AI disabled.

- Do not silently modify already approved indicator targets or formulas.

- Do not remove auditability to simplify implementation.

- Do not return a “done” status if acceptance tests are failing.

### Acceptance evidence

The final IDE response for this prompt should include the exact tests executed and their result, important API/UI examples, any migration or environment variable introduced, and a concise verification checklist. Where the prompt creates a visible screen, provide screenshots or render verification. Where it creates a calculation/data service, provide sample deterministic input/output demonstrating the contract.

## F.20 Prompt 20: AI Analyst and Ask the Data

Objective: Build evidence-first natural-language analysis, Explain This, key findings and recommendations.

### Context the prompt must restate

The prompt must remind the IDE that this is one increment in a national, role-based health performance platform whose initial release is MNCH. It must reference the existing repository and the relevant preceding phases, insist on deterministic calculation and server-side authorisation, and explicitly preserve previously approved regression behaviour. The IDE should inspect existing code before adding new abstractions so that each phase extends rather than replaces working foundations.

### Required deliverables

- Question workflow, deterministic evidence queries, structured AI response and evidence links.

- Automated tests for normal, missing-data and permission/error states.

- Developer documentation that explains configuration or migrations added by the prompt.

- Short handoff noting changed files, tests run, unresolved decisions and next-phase dependencies.

### Implementation depth expected

This prompt should not stop at interface stubs. For AI Analyst and Ask the Data, the implementation must include domain/service logic, API or UI integration as appropriate, persistence where required, validation, typed/structured request and response contracts, error handling, audit/logging hooks, and test coverage. Mock data may be used only in automated tests or isolated development fixtures; production screens and services should be wired to the real internal interfaces created in earlier phases.

### Guardrails

- AI cannot broaden permissions.

- Unsupported causal questions are labelled unsupported.

- Do not silently modify already approved indicator targets or formulas.

- Do not remove auditability to simplify implementation.

- Do not return a “done” status if acceptance tests are failing.

### Acceptance evidence

The final IDE response for this prompt should include the exact tests executed and their result, important API/UI examples, any migration or environment variable introduced, and a concise verification checklist. Where the prompt creates a visible screen, provide screenshots or render verification. Where it creates a calculation/data service, provide sample deterministic input/output demonstrating the contract.

## F.21 Prompt 21: Excel Generator

Objective: Build deterministic workbook generation with Scorecard, Calculations, Raw Data, Population, Methodology and Quality sheets.

### Context the prompt must restate

The prompt must remind the IDE that this is one increment in a national, role-based health performance platform whose initial release is MNCH. It must reference the existing repository and the relevant preceding phases, insist on deterministic calculation and server-side authorisation, and explicitly preserve previously approved regression behaviour. The IDE should inspect existing code before adding new abstractions so that each phase extends rather than replaces working foundations.

### Required deliverables

- Styled reproducible XLSX with RAG colours and audit metadata.

- Automated tests for normal, missing-data and permission/error states.

- Developer documentation that explains configuration or migrations added by the prompt.

- Short handoff noting changed files, tests run, unresolved decisions and next-phase dependencies.

### Implementation depth expected

This prompt should not stop at interface stubs. For Excel Generator, the implementation must include domain/service logic, API or UI integration as appropriate, persistence where required, validation, typed/structured request and response contracts, error handling, audit/logging hooks, and test coverage. Mock data may be used only in automated tests or isolated development fixtures; production screens and services should be wired to the real internal interfaces created in earlier phases.

### Guardrails

- Values match calculation run exactly.

- No AI-generated workbook structure.

- Do not silently modify already approved indicator targets or formulas.

- Do not remove auditability to simplify implementation.

- Do not return a “done” status if acceptance tests are failing.

### Acceptance evidence

The final IDE response for this prompt should include the exact tests executed and their result, important API/UI examples, any migration or environment variable introduced, and a concise verification checklist. Where the prompt creates a visible screen, provide screenshots or render verification. Where it creates a calculation/data service, provide sample deterministic input/output demonstrating the contract.

## F.22 Prompt 22: PowerPoint Generator

Objective: Build versioned PowerPoint templates and deterministic chart/table population for approved slide families.

### Context the prompt must restate

The prompt must remind the IDE that this is one increment in a national, role-based health performance platform whose initial release is MNCH. It must reference the existing repository and the relevant preceding phases, insist on deterministic calculation and server-side authorisation, and explicitly preserve previously approved regression behaviour. The IDE should inspect existing code before adding new abstractions so that each phase extends rather than replaces working foundations.

### Required deliverables

- PPTX generation service and template admin workflow.

- Automated tests for normal, missing-data and permission/error states.

- Developer documentation that explains configuration or migrations added by the prompt.

- Short handoff noting changed files, tests run, unresolved decisions and next-phase dependencies.

### Implementation depth expected

This prompt should not stop at interface stubs. For PowerPoint Generator, the implementation must include domain/service logic, API or UI integration as appropriate, persistence where required, validation, typed/structured request and response contracts, error handling, audit/logging hooks, and test coverage. Mock data may be used only in automated tests or isolated development fixtures; production screens and services should be wired to the real internal interfaces created in earlier phases.

### Guardrails

- AI only fills designated narrative fields.

- Presentation remains readable and visually consistent.

- Do not silently modify already approved indicator targets or formulas.

- Do not remove auditability to simplify implementation.

- Do not return a “done” status if acceptance tests are failing.

### Acceptance evidence

The final IDE response for this prompt should include the exact tests executed and their result, important API/UI examples, any migration or environment variable introduced, and a concise verification checklist. Where the prompt creates a visible screen, provide screenshots or render verification. Where it creates a calculation/data service, provide sample deterministic input/output demonstrating the contract.

## F.23 Prompt 23: Narrative Report Generator

Objective: Build Word/PDF report composition from deterministic tables/charts and AI-grounded prose.

### Context the prompt must restate

The prompt must remind the IDE that this is one increment in a national, role-based health performance platform whose initial release is MNCH. It must reference the existing repository and the relevant preceding phases, insist on deterministic calculation and server-side authorisation, and explicitly preserve previously approved regression behaviour. The IDE should inspect existing code before adding new abstractions so that each phase extends rather than replaces working foundations.

### Required deliverables

- Report job/template pipeline, citations to evidence and downloadable output.

- Automated tests for normal, missing-data and permission/error states.

- Developer documentation that explains configuration or migrations added by the prompt.

- Short handoff noting changed files, tests run, unresolved decisions and next-phase dependencies.

### Implementation depth expected

This prompt should not stop at interface stubs. For Narrative Report Generator, the implementation must include domain/service logic, API or UI integration as appropriate, persistence where required, validation, typed/structured request and response contracts, error handling, audit/logging hooks, and test coverage. Mock data may be used only in automated tests or isolated development fixtures; production screens and services should be wired to the real internal interfaces created in earlier phases.

### Guardrails

- Report records run ID and methodology version.

- Sensitive case detail excluded by default.

- Do not silently modify already approved indicator targets or formulas.

- Do not remove auditability to simplify implementation.

- Do not return a “done” status if acceptance tests are failing.

### Acceptance evidence

The final IDE response for this prompt should include the exact tests executed and their result, important API/UI examples, any migration or environment variable introduced, and a concise verification checklist. Where the prompt creates a visible screen, provide screenshots or render verification. Where it creates a calculation/data service, provide sample deterministic input/output demonstrating the contract.

## F.24 Prompt 24: Full Regression and Validation

Objective: Create gold-standard fixtures from validated Acholi calculations and end-to-end permission/export tests.

### Context the prompt must restate

The prompt must remind the IDE that this is one increment in a national, role-based health performance platform whose initial release is MNCH. It must reference the existing repository and the relevant preceding phases, insist on deterministic calculation and server-side authorisation, and explicitly preserve previously approved regression behaviour. The IDE should inspect existing code before adding new abstractions so that each phase extends rather than replaces working foundations.

### Required deliverables

- Automated regression suite and QA report.

- Automated tests for normal, missing-data and permission/error states.

- Developer documentation that explains configuration or migrations added by the prompt.

- Short handoff noting changed files, tests run, unresolved decisions and next-phase dependencies.

### Implementation depth expected

This prompt should not stop at interface stubs. For Full Regression and Validation, the implementation must include domain/service logic, API or UI integration as appropriate, persistence where required, validation, typed/structured request and response contracts, error handling, audit/logging hooks, and test coverage. Mock data may be used only in automated tests or isolated development fixtures; production screens and services should be wired to the real internal interfaces created in earlier phases.

### Guardrails

- Any value mismatch fails release.

- Test both ordinary and BLUE edge cases.

- Do not silently modify already approved indicator targets or formulas.

- Do not remove auditability to simplify implementation.

- Do not return a “done” status if acceptance tests are failing.

### Acceptance evidence

The final IDE response for this prompt should include the exact tests executed and their result, important API/UI examples, any migration or environment variable introduced, and a concise verification checklist. Where the prompt creates a visible screen, provide screenshots or render verification. Where it creates a calculation/data service, provide sample deterministic input/output demonstrating the contract.

## F.25 Prompt 25: Security, Performance and Reliability

Objective: Harden auth, secrets, query limits, caches, background jobs, MPDSR privacy, rate limiting, monitoring and backups.

### Context the prompt must restate

The prompt must remind the IDE that this is one increment in a national, role-based health performance platform whose initial release is MNCH. It must reference the existing repository and the relevant preceding phases, insist on deterministic calculation and server-side authorisation, and explicitly preserve previously approved regression behaviour. The IDE should inspect existing code before adding new abstractions so that each phase extends rather than replaces working foundations.

### Required deliverables

- Security/performance checklist, load tests, threat mitigations and operations dashboard.

- Automated tests for normal, missing-data and permission/error states.

- Developer documentation that explains configuration or migrations added by the prompt.

- Short handoff noting changed files, tests run, unresolved decisions and next-phase dependencies.

### Implementation depth expected

This prompt should not stop at interface stubs. For Security, Performance and Reliability, the implementation must include domain/service logic, API or UI integration as appropriate, persistence where required, validation, typed/structured request and response contracts, error handling, audit/logging hooks, and test coverage. Mock data may be used only in automated tests or isolated development fixtures; production screens and services should be wired to the real internal interfaces created in earlier phases.

### Guardrails

- National-scale queries must not depend on synchronous upstream calls.

- Sensitive fields excluded from logs.

- Do not silently modify already approved indicator targets or formulas.

- Do not remove auditability to simplify implementation.

- Do not return a “done” status if acceptance tests are failing.

### Acceptance evidence

The final IDE response for this prompt should include the exact tests executed and their result, important API/UI examples, any migration or environment variable introduced, and a concise verification checklist. Where the prompt creates a visible screen, provide screenshots or render verification. Where it creates a calculation/data service, provide sample deterministic input/output demonstrating the contract.

## F.26 Prompt 26: Production Deployment and Documentation

Objective: Package deployment, migrations, environment setup, admin/user guides, disaster recovery and handoff.

### Context the prompt must restate

The prompt must remind the IDE that this is one increment in a national, role-based health performance platform whose initial release is MNCH. It must reference the existing repository and the relevant preceding phases, insist on deterministic calculation and server-side authorisation, and explicitly preserve previously approved regression behaviour. The IDE should inspect existing code before adding new abstractions so that each phase extends rather than replaces working foundations.

### Required deliverables

- Production deployment scripts, runbooks, onboarding docs and release checklist.

- Automated tests for normal, missing-data and permission/error states.

- Developer documentation that explains configuration or migrations added by the prompt.

- Short handoff noting changed files, tests run, unresolved decisions and next-phase dependencies.

### Implementation depth expected

This prompt should not stop at interface stubs. For Production Deployment and Documentation, the implementation must include domain/service logic, API or UI integration as appropriate, persistence where required, validation, typed/structured request and response contracts, error handling, audit/logging hooks, and test coverage. Mock data may be used only in automated tests or isolated development fixtures; production screens and services should be wired to the real internal interfaces created in earlier phases.

### Guardrails

- No unresolved default secrets.

- Rollback and backup restoration are tested.

- Do not silently modify already approved indicator targets or formulas.

- Do not remove auditability to simplify implementation.

- Do not return a “done” status if acceptance tests are failing.

### Acceptance evidence

The final IDE response for this prompt should include the exact tests executed and their result, important API/UI examples, any migration or environment variable introduced, and a concise verification checklist. Where the prompt creates a visible screen, provide screenshots or render verification. Where it creates a calculation/data service, provide sample deterministic input/output demonstrating the contract.

# Appendix G. Detailed Technical Patterns and Edge-Case Handling

## G.1 Population resolution

Given geography, period and indicator version, resolve denominator year from financial-year rule; find approved population version; apply target coefficient and period fraction; return denominator plus provenance. If no population exists, return a typed missing-denominator result rather than zero. Historical calculation runs retain their population version ID.

Implementation expectation: represent this behaviour in a reusable service or policy object with explicit typed outcomes and automated tests. The API should return enough metadata for the user interface and exports to explain the decision. Logging should record failures and rule IDs without leaking sensitive payloads. Where a rule can change over time, keep it configurable/versioned and bind calculation runs to the version used.

- Test a normal valid case.

- Test a missing/invalid case.

- Test a boundary value exactly on the threshold.

- Test parent/child scope behaviour where relevant.

- Verify the generated evidence package explains the result.

## G.2 Parent aggregation

For each child unit, obtain raw numerator/denominator components. Sum valid components across authorised descendants. Calculate parent value once from summed components. Record child units excluded for missing/invalid components. Never average displayed percentages to produce a region or national value.

Implementation expectation: represent this behaviour in a reusable service or policy object with explicit typed outcomes and automated tests. The API should return enough metadata for the user interface and exports to explain the decision. Logging should record failures and rule IDs without leaking sensitive payloads. Where a rule can change over time, keep it configurable/versioned and bind calculation runs to the version used.

- Test a normal valid case.

- Test a missing/invalid case.

- Test a boundary value exactly on the threshold.

- Test parent/child scope behaviour where relevant.

- Verify the generated evidence package explains the result.

## G.3 Event cohorting

Define the cohort using the semantic date of death and selected period. Query notification/review events associated with the programme/stage and geography. Count only COMPLETED events for completed numerators; keep ACTIVE events in separate workflow metrics. Invalid chronology is flagged and excluded from timely numerators.

Implementation expectation: represent this behaviour in a reusable service or policy object with explicit typed outcomes and automated tests. The API should return enough metadata for the user interface and exports to explain the decision. Logging should record failures and rule IDs without leaking sensitive payloads. Where a rule can change over time, keep it configurable/versioned and bind calculation runs to the version used.

- Test a normal valid case.

- Test a missing/invalid case.

- Test a boundary value exactly on the threshold.

- Test parent/child scope behaviour where relevant.

- Verify the generated evidence package explains the result.

## G.4 Notification timeliness

If exact notification timestamp exists, compute elapsed hours and test \<=24 hours. If only calendar date exists, use same/next calendar day as the configured proxy and mark the method in evidence. Records with malformed/missing death date are not labelled late; they are non-assessable and contribute to data-quality counts.

Implementation expectation: represent this behaviour in a reusable service or policy object with explicit typed outcomes and automated tests. The API should return enough metadata for the user interface and exports to explain the decision. Logging should record failures and rule IDs without leaking sensitive payloads. Where a rule can change over time, keep it configurable/versioned and bind calculation runs to the version used.

- Test a normal valid case.

- Test a missing/invalid case.

- Test a boundary value exactly on the threshold.

- Test parent/child scope behaviour where relevant.

- Verify the generated evidence package explains the result.

## G.5 Review timeliness

Use the configured review-event date semantics and compute calendar/elapsed days from death. Completed reviews 0-7 days are timely. Review date before death is an impossible chronology flag and cannot count timely. The denominator remains total reported deaths for end-to-end programme performance.

Implementation expectation: represent this behaviour in a reusable service or policy object with explicit typed outcomes and automated tests. The API should return enough metadata for the user interface and exports to explain the decision. Logging should record failures and rule IDs without leaking sensitive payloads. Where a rule can change over time, keep it configurable/versioned and bind calculation runs to the version used.

- Test a normal valid case.

- Test a missing/invalid case.

- Test a boundary value exactly on the threshold.

- Test parent/child scope behaviour where relevant.

- Verify the generated evidence package explains the result.

## G.6 RAG/BLUE classification

Calculate numeric value first, then run quality overrides and threshold classifier. A BLUE override may take precedence when a bounded measure is impossible or a reconciliation mismatch makes percentage interpretation unsafe. Preserve numeric value and reason. N/A is distinct from zero.

Implementation expectation: represent this behaviour in a reusable service or policy object with explicit typed outcomes and automated tests. The API should return enough metadata for the user interface and exports to explain the decision. Logging should record failures and rule IDs without leaking sensitive payloads. Where a rule can change over time, keep it configurable/versioned and bind calculation runs to the version used.

- Test a normal valid case.

- Test a missing/invalid case.

- Test a boundary value exactly on the threshold.

- Test parent/child scope behaviour where relevant.

- Verify the generated evidence package explains the result.

## G.7 Comparison direction

For higher-is-better indicators, positive change is improvement. For lower-is-better indicators, negative change is improvement. For desired-range indicators, calculate distance/status relative to range rather than treating raw direction as improvement. Display both numerical change and status transition.

Implementation expectation: represent this behaviour in a reusable service or policy object with explicit typed outcomes and automated tests. The API should return enough metadata for the user interface and exports to explain the decision. Logging should record failures and rule IDs without leaking sensitive payloads. Where a rule can change over time, keep it configurable/versioned and bind calculation runs to the version used.

- Test a normal valid case.

- Test a missing/invalid case.

- Test a boundary value exactly on the threshold.

- Test parent/child scope behaviour where relevant.

- Verify the generated evidence package explains the result.

## G.8 Contribution analysis

For burden counts, contribution = child count / parent count. For missed-target analysis, compute target numerator requirement minus actual numerator per child, floored at zero when appropriate. Rank child units by absolute contribution. Do not label share ratios as epidemiological risk ratios.

Implementation expectation: represent this behaviour in a reusable service or policy object with explicit typed outcomes and automated tests. The API should return enough metadata for the user interface and exports to explain the decision. Logging should record failures and rule IDs without leaking sensitive payloads. Where a rule can change over time, keep it configurable/versioned and bind calculation runs to the version used.

- Test a normal valid case.

- Test a missing/invalid case.

- Test a boundary value exactly on the threshold.

- Test parent/child scope behaviour where relevant.

- Verify the generated evidence package explains the result.

## G.9 Data freshness

Every cached dataset/calculation run stores source extraction time. UI displays last refresh. If upstream sync fails, serve last validated cache with stale warning according to policy. A user-initiated export binds to the current run so figures do not shift during generation.

Implementation expectation: represent this behaviour in a reusable service or policy object with explicit typed outcomes and automated tests. The API should return enough metadata for the user interface and exports to explain the decision. Logging should record failures and rule IDs without leaking sensitive payloads. Where a rule can change over time, keep it configurable/versioned and bind calculation runs to the version used.

- Test a normal valid case.

- Test a missing/invalid case.

- Test a boundary value exactly on the threshold.

- Test parent/child scope behaviour where relevant.

- Verify the generated evidence package explains the result.

## G.10 AI evidence safety

Build evidence from calculated values and approved aggregates. Apply permission and sensitivity filter before provider routing. Strip patient identifiers, usernames, exact sensitive narratives and unnecessary dates. Store provider/model/task metadata and evidence hash for audit. Validate generated numbers against evidence before display.

Implementation expectation: represent this behaviour in a reusable service or policy object with explicit typed outcomes and automated tests. The API should return enough metadata for the user interface and exports to explain the decision. Logging should record failures and rule IDs without leaking sensitive payloads. Where a rule can change over time, keep it configurable/versioned and bind calculation runs to the version used.

- Test a normal valid case.

- Test a missing/invalid case.

- Test a boundary value exactly on the threshold.

- Test parent/child scope behaviour where relevant.

- Verify the generated evidence package explains the result.

## G.11 Export reproducibility

Export job receives calculation_run_id plus template_version_id. It queries materialised calculated/evidence outputs, never re-fetches DHIS2 independently. Generated file embeds scope, period, source refresh and methodology/version references. Regeneration from the same run should reproduce figures.

Implementation expectation: represent this behaviour in a reusable service or policy object with explicit typed outcomes and automated tests. The API should return enough metadata for the user interface and exports to explain the decision. Logging should record failures and rule IDs without leaking sensitive payloads. Where a rule can change over time, keep it configurable/versioned and bind calculation runs to the version used.

- Test a normal valid case.

- Test a missing/invalid case.

- Test a boundary value exactly on the threshold.

- Test parent/child scope behaviour where relevant.

- Verify the generated evidence package explains the result.

## G.12 Facility catchment population

When missing, population-derived indicators return requires_population=true. UI offers population entry only to authorised users. Save creates a version with year/source/note. After approval, affected indicators recalculate; service-derived indicators were available throughout.

Implementation expectation: represent this behaviour in a reusable service or policy object with explicit typed outcomes and automated tests. The API should return enough metadata for the user interface and exports to explain the decision. Logging should record failures and rule IDs without leaking sensitive payloads. Where a rule can change over time, keep it configurable/versioned and bind calculation runs to the version used.

- Test a normal valid case.

- Test a missing/invalid case.

- Test a boundary value exactly on the threshold.

- Test parent/child scope behaviour where relevant.

- Verify the generated evidence package explains the result.

## G.13 No-data versus zero

A source absence is null/no-data; a reported value of 0 is a real zero. The ingestion layer preserves this distinction. Trends show gaps for missing values. Scorecards show N/A/no data, not 0%, unless the numerator is explicitly reported zero against a valid denominator.

Implementation expectation: represent this behaviour in a reusable service or policy object with explicit typed outcomes and automated tests. The API should return enough metadata for the user interface and exports to explain the decision. Logging should record failures and rule IDs without leaking sensitive payloads. Where a rule can change over time, keep it configurable/versioned and bind calculation runs to the version used.

- Test a normal valid case.

- Test a missing/invalid case.

- Test a boundary value exactly on the threshold.

- Test parent/child scope behaviour where relevant.

- Verify the generated evidence package explains the result.

## G.14 Small numbers

For mortality and other rare outcomes, show underlying count beside ratio. Avoid ranking or narrative exaggeration when denominators/counts are tiny. Maternal cause analysis defaults to higher aggregation and suppresses potentially identifying combinations according to privacy rules.

Implementation expectation: represent this behaviour in a reusable service or policy object with explicit typed outcomes and automated tests. The API should return enough metadata for the user interface and exports to explain the decision. Logging should record failures and rule IDs without leaking sensitive payloads. Where a rule can change over time, keep it configurable/versioned and bind calculation runs to the version used.

- Test a normal valid case.

- Test a missing/invalid case.

- Test a boundary value exactly on the threshold.

- Test parent/child scope behaviour where relevant.

- Verify the generated evidence package explains the result.

## G.15 Metadata drift

Scheduled metadata sync detects renamed/replaced DHIS2 elements and unmapped UIDs. Mappings are versioned. If a required UID disappears, calculation is blocked with mapping error instead of silently using another data element. Administrators review and publish mapping updates.

Implementation expectation: represent this behaviour in a reusable service or policy object with explicit typed outcomes and automated tests. The API should return enough metadata for the user interface and exports to explain the decision. Logging should record failures and rule IDs without leaking sensitive payloads. Where a rule can change over time, keep it configurable/versioned and bind calculation runs to the version used.

- Test a normal valid case.

- Test a missing/invalid case.

- Test a boundary value exactly on the threshold.

- Test parent/child scope behaviour where relevant.

- Verify the generated evidence package explains the result.

# Appendix H. API Response and Evidence Examples

## H.1 Scorecard response example

A scorecard endpoint should return metadata and rows rather than only an array of percentages. Example conceptual payload fields: calculation_run_id, geography, period, programme, source_refreshed_at, indicator_versions, rows\[\].org_unit, rows\[\].indicators\[\].indicator_id, numerator, denominator, raw_value, display_value, unit, target, status, quality_flags and comparison. This allows the front end to render the table without reverse-engineering methodology from display strings.

## H.2 Evidence drawer response

The evidence endpoint for one cell should include formula text, semantic numerator/denominator labels, values, population source/year if applicable, threshold rule, current/prior values, status transition, child-unit contributors, time-series points and quality flags. It should also include a human-readable “method note” that can be displayed without AI. This endpoint is the canonical source for the Explain This feature and for spreadsheet methodology/calculation sheets.

## H.3 MPDSR process response

The MPDSR endpoint should separate reported_count, completed_notification_count, timely_notification_count, completed_review_count, timely_review_count, active_notification_count, active_review_count, non_assessable_timeliness_count and reconciliation flags. It should return the method used for notification timeliness (timestamp_24h or calendar_day_proxy) and the review timeliness window. Maternal and perinatal targets are returned from their indicator versions rather than hard-coded in the front end.

## H.4 Map response

A map API can return GeoJSON FeatureCollection where each feature has internal org_unit_id, name, level, indicator display value, raw value, status, no_data flag and minimal tooltip metadata. Sensitive event details are never embedded in map properties. Large geometry can be served from a tile/vector layer while analytical properties are joined by org_unit_id.

## H.5 Export job response

POST /exports/powerpoint returns job_id, requested scope, template version and calculation run. GET /jobs/{id} returns queued/running/succeeded/failed, progress if available, failure code safe for users, and download URL after success. The worker does not recalculate from upstream DHIS2; it reads the specified run.

# Appendix I. End-to-End User Scenarios

## I.1 National MNCH review

A national analyst logs in and lands on Uganda. They select FY2025/26 and MNCH. The page loads national KPIs, a regional map and regional scorecard. They notice ANC4 is below target nationally, click the ANC4 card, inspect contributing regions and then drill into Acholi. They generate a national PowerPoint summary using the approved template. The exported ANC4 value, map colours and narrative findings all reference the same calculation run.

Acceptance condition: every navigation and output in this scenario must respect the authenticated user’s geography/programme/action scope, preserve one consistent analytical state and expose sufficient provenance to explain the displayed figures.

## I.2 Regional district prioritisation

A regional analyst lands on Acholi. The district map and scorecard show district variation. They select ANC8 and ask “Which districts contribute most to the gap?” Deterministic analytics calculate missed-target contribution and AI explains the top contributors. The analyst drills into Pader to see which facilities drive low ANC8.

Acceptance condition: every navigation and output in this scenario must respect the authenticated user’s geography/programme/action scope, preserve one consistent analytical state and expose sufficient provenance to explain the displayed figures.

## I.3 District facility analysis

A Pader district user lands on Pader. The facility table shows ANC, delivery, immunisation and selected outcome measures. They sort by ANC8 and filter to HC III facilities. The top/bottom panel updates. A facility with missing catchment population shows N/A for ANC coverage but still shows first-trimester and Hb measures. The user enters the approved population with source note and the affected coverage indicators recalculate.

Acceptance condition: every navigation and output in this scenario must respect the authenticated user’s geography/programme/action scope, preserve one consistent analytical state and expose sufficient provenance to explain the displayed figures.

## I.4 MPDSR operational follow-up

An authorised MPDSR user opens the process scorecard. The perinatal review-on-time value is red. They inspect active reviews, filter to the facilities with the largest backlog, and see date-quality flags. The user can view permitted event-level operational records, but the AI summary receives only aggregate backlog counts and approved cause statistics.

Acceptance condition: every navigation and output in this scenario must respect the authenticated user’s geography/programme/action scope, preserve one consistent analytical state and expose sufficient provenance to explain the displayed figures.

## I.5 Data-quality reconciliation

A district shows 80 completed perinatal notifications against 73 reported deaths. The scorecard displays 109.6% as BLUE rather than green. The evidence drawer explains the mismatch and recommends checking duplicates/under-reporting. The system does not cap the value or automatically delete any record.

Acceptance condition: every navigation and output in this scenario must respect the authenticated user’s geography/programme/action scope, preserve one consistent analytical state and expose sufficient provenance to explain the displayed figures.

## I.6 Facility report generation

A facility user opens their facility profile, sees current scorecard/trends and clicks Generate Facility Report. The report job uses the active calculation run, deterministic tables/charts and evidence-grounded AI summary. The resulting file includes source refresh time, population year/source and indicator methodology.

Acceptance condition: every navigation and output in this scenario must respect the authenticated user’s geography/programme/action scope, preserve one consistent analytical state and expose sufficient provenance to explain the displayed figures.

# Appendix J. Detailed Acceptance Matrix and Definition of Done

This appendix is intentionally operational. A feature is not “done” because it renders or because an endpoint returns HTTP 200. Each component must meet analytical, security, provenance, usability and regression requirements. The IDE should use these definitions of done in addition to prompt-specific acceptance tests.

| **Component**                | **Minimum definition of done**                                                                                                                                           |
|------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Organisation hierarchy       | Correct parent-child structure, valid level labels, authorised descendants only, and stable internal IDs even if DHIS2 names change.                                     |
| Population resolver          | Correct year/version/source resolution, period scaling where applicable, no silent fallback to another year, and explicit missing-population state.                      |
| Facility population override | Permission-checked entry, source/year/note captured, audit trail created, historical runs unchanged, and only affected indicators recalculated.                          |
| Indicator registry           | Versioned formula, target, direction, unit, period rule and source mapping; historical versions remain queryable and old runs remain reproducible.                       |
| Calculation engine           | Exact arithmetic using full precision, correct denominator type, correct parent aggregation and deterministic output for same inputs/version.                            |
| Threshold engine             | Correct higher/lower/range logic, exact boundary handling, BLUE override behaviour and no frontend reimplementation of thresholds.                                       |
| DHIS2 aggregate sync         | Mapped UIDs, period/org-unit handling, retry/cache behaviour, freshness metadata and missing response preserved as missing rather than zero.                             |
| Event Analytics sync         | Program/stage filters, event rows/aggregates, approved semantic mappings, pagination and extraction provenance.                                                          |
| Tracker current-state sync   | ACTIVE/COMPLETED preserved, current event dataValues available where authorised, and refresh path separated from analytics-table lag.                                    |
| Data-quality rules           | Each flag has rule ID, severity, evidence, geography/period, timestamps, resolution state and no automatic deletion/correction.                                          |
| National dashboard           | National authorised landing, consistent run across cards/map/table/trends, correct regional drill-down and reproducible exports.                                         |
| Regional dashboard           | District/city peer units, aggregate-from-components logic, map/table consistency, priority calculation and district drill-down.                                          |
| District facility dashboard  | Complete facility list in scope, facility-level table and ranking, data-quality-aware ranking and click-through to facility profile.                                     |
| Facility dashboard           | Population-aware indicators, service-derived measures remain available without population, trends/alerts and scope-correct exports.                                      |
| ANC module                   | All agreed formulas/thresholds, inverse teenage pregnancy logic, IFA \>100 flagging, continuum and year comparison.                                                      |
| Intrapartum module           | Correct 4.85% expected-delivery denominator, C-section desired range, mortality units, KMC/resuscitation BLUE rules and small-count context.                             |
| Immunization module          | Correct target coefficients including MV4 4.3%, period scaling, dropout/continuum and no invented programme thresholds.                                                  |
| MPDSR process module         | Reported/notified/reviewed counts, COMPLETED-only numerators, ACTIVE counts separate, timeliness methods explicit and maternal/perinatal targets distinct.               |
| MPDSR causes                 | Perinatal/maternal privacy rules, overlapping cause categories not forced into pie totals, documentation completeness visible and no case-identifying narrative leakage. |
| Trend engine                 | Correct period denominator, missing values as gaps, inverse interpretation, target overlays and exportable data.                                                         |
| Contribution/Pareto          | Transparent denominator, absolute contribution logic, no misuse as risk ratio and correct child-to-parent reconciliation.                                                |
| Map engine                   | Authorised geometries only, correct RAG from indicator rules, drill-down, no-data representation and unmapped units not dropped from other views.                        |
| AI Gateway                   | Provider abstraction, privacy filter, evidence package, cost/usage log, timeouts/fallback and no-AI mode.                                                                |
| Ask the Data                 | Deterministic authorised evidence retrieval before generation, evidence links, unsupported questions acknowledged and no permission expansion.                           |
| Excel export                 | Screen-matching values/status, calculation sheet, methodology, population/source, raw data where permitted and quality sheet.                                            |
| PowerPoint export            | Approved template version, readable charts/tables, deterministic numbers/colours and AI restricted to designated narrative fields.                                       |
| Narrative report             | Verified evidence and charts, methodology/source/run metadata, privacy controls and no unsupported numerical statements.                                                 |
| Audit log                    | Material config/security changes recorded with actor/time/before/after and protected from ordinary editing.                                                              |
| Observability                | Sync freshness, failures, queues, AI errors/costs, DB performance and safe alerting visible to administrators.                                                           |
| Production deployment        | Documented environments, migrations, secrets, backups, rollback, disaster-recovery test and admin/user handoff material.                                                 |

## J.1 Organisation hierarchy

Correct parent-child structure, valid level labels, authorised descendants only, and stable internal IDs even if DHIS2 names change.

Verification should include both an automated test and an operator-visible check where the component affects the interface or official outputs. The implementation should expose enough metadata to diagnose a failure without reading database rows manually. Any discrepancy between dashboard, API, Excel or PowerPoint is a release blocker until the underlying calculation run and template behaviour are reconciled.

- Functional test covers the expected path and at least one failure/edge path.

- Permission test confirms the feature cannot be used outside the authorised geography/programme/action scope.

- Provenance test confirms source refresh, indicator version and calculation run are traceable.

- Regression test confirms previously validated Acholi figures remain unchanged unless an approved methodology version changes them.

- User-facing state distinguishes no data, zero, stale data, data-quality problem and normal performance.

## J.2 Population resolver

Correct year/version/source resolution, period scaling where applicable, no silent fallback to another year, and explicit missing-population state.

Verification should include both an automated test and an operator-visible check where the component affects the interface or official outputs. The implementation should expose enough metadata to diagnose a failure without reading database rows manually. Any discrepancy between dashboard, API, Excel or PowerPoint is a release blocker until the underlying calculation run and template behaviour are reconciled.

- Functional test covers the expected path and at least one failure/edge path.

- Permission test confirms the feature cannot be used outside the authorised geography/programme/action scope.

- Provenance test confirms source refresh, indicator version and calculation run are traceable.

- Regression test confirms previously validated Acholi figures remain unchanged unless an approved methodology version changes them.

- User-facing state distinguishes no data, zero, stale data, data-quality problem and normal performance.

## J.3 Facility population override

Permission-checked entry, source/year/note captured, audit trail created, historical runs unchanged, and only affected indicators recalculated.

Verification should include both an automated test and an operator-visible check where the component affects the interface or official outputs. The implementation should expose enough metadata to diagnose a failure without reading database rows manually. Any discrepancy between dashboard, API, Excel or PowerPoint is a release blocker until the underlying calculation run and template behaviour are reconciled.

- Functional test covers the expected path and at least one failure/edge path.

- Permission test confirms the feature cannot be used outside the authorised geography/programme/action scope.

- Provenance test confirms source refresh, indicator version and calculation run are traceable.

- Regression test confirms previously validated Acholi figures remain unchanged unless an approved methodology version changes them.

- User-facing state distinguishes no data, zero, stale data, data-quality problem and normal performance.

## J.4 Indicator registry

Versioned formula, target, direction, unit, period rule and source mapping; historical versions remain queryable and old runs remain reproducible.

Verification should include both an automated test and an operator-visible check where the component affects the interface or official outputs. The implementation should expose enough metadata to diagnose a failure without reading database rows manually. Any discrepancy between dashboard, API, Excel or PowerPoint is a release blocker until the underlying calculation run and template behaviour are reconciled.

- Functional test covers the expected path and at least one failure/edge path.

- Permission test confirms the feature cannot be used outside the authorised geography/programme/action scope.

- Provenance test confirms source refresh, indicator version and calculation run are traceable.

- Regression test confirms previously validated Acholi figures remain unchanged unless an approved methodology version changes them.

- User-facing state distinguishes no data, zero, stale data, data-quality problem and normal performance.

## J.5 Calculation engine

Exact arithmetic using full precision, correct denominator type, correct parent aggregation and deterministic output for same inputs/version.

Verification should include both an automated test and an operator-visible check where the component affects the interface or official outputs. The implementation should expose enough metadata to diagnose a failure without reading database rows manually. Any discrepancy between dashboard, API, Excel or PowerPoint is a release blocker until the underlying calculation run and template behaviour are reconciled.

- Functional test covers the expected path and at least one failure/edge path.

- Permission test confirms the feature cannot be used outside the authorised geography/programme/action scope.

- Provenance test confirms source refresh, indicator version and calculation run are traceable.

- Regression test confirms previously validated Acholi figures remain unchanged unless an approved methodology version changes them.

- User-facing state distinguishes no data, zero, stale data, data-quality problem and normal performance.

## J.6 Threshold engine

Correct higher/lower/range logic, exact boundary handling, BLUE override behaviour and no frontend reimplementation of thresholds.

Verification should include both an automated test and an operator-visible check where the component affects the interface or official outputs. The implementation should expose enough metadata to diagnose a failure without reading database rows manually. Any discrepancy between dashboard, API, Excel or PowerPoint is a release blocker until the underlying calculation run and template behaviour are reconciled.

- Functional test covers the expected path and at least one failure/edge path.

- Permission test confirms the feature cannot be used outside the authorised geography/programme/action scope.

- Provenance test confirms source refresh, indicator version and calculation run are traceable.

- Regression test confirms previously validated Acholi figures remain unchanged unless an approved methodology version changes them.

- User-facing state distinguishes no data, zero, stale data, data-quality problem and normal performance.

## J.7 DHIS2 aggregate sync

Mapped UIDs, period/org-unit handling, retry/cache behaviour, freshness metadata and missing response preserved as missing rather than zero.

Verification should include both an automated test and an operator-visible check where the component affects the interface or official outputs. The implementation should expose enough metadata to diagnose a failure without reading database rows manually. Any discrepancy between dashboard, API, Excel or PowerPoint is a release blocker until the underlying calculation run and template behaviour are reconciled.

- Functional test covers the expected path and at least one failure/edge path.

- Permission test confirms the feature cannot be used outside the authorised geography/programme/action scope.

- Provenance test confirms source refresh, indicator version and calculation run are traceable.

- Regression test confirms previously validated Acholi figures remain unchanged unless an approved methodology version changes them.

- User-facing state distinguishes no data, zero, stale data, data-quality problem and normal performance.

## J.8 Event Analytics sync

Program/stage filters, event rows/aggregates, approved semantic mappings, pagination and extraction provenance.

Verification should include both an automated test and an operator-visible check where the component affects the interface or official outputs. The implementation should expose enough metadata to diagnose a failure without reading database rows manually. Any discrepancy between dashboard, API, Excel or PowerPoint is a release blocker until the underlying calculation run and template behaviour are reconciled.

- Functional test covers the expected path and at least one failure/edge path.

- Permission test confirms the feature cannot be used outside the authorised geography/programme/action scope.

- Provenance test confirms source refresh, indicator version and calculation run are traceable.

- Regression test confirms previously validated Acholi figures remain unchanged unless an approved methodology version changes them.

- User-facing state distinguishes no data, zero, stale data, data-quality problem and normal performance.

## J.9 Tracker current-state sync

ACTIVE/COMPLETED preserved, current event dataValues available where authorised, and refresh path separated from analytics-table lag.

Verification should include both an automated test and an operator-visible check where the component affects the interface or official outputs. The implementation should expose enough metadata to diagnose a failure without reading database rows manually. Any discrepancy between dashboard, API, Excel or PowerPoint is a release blocker until the underlying calculation run and template behaviour are reconciled.

- Functional test covers the expected path and at least one failure/edge path.

- Permission test confirms the feature cannot be used outside the authorised geography/programme/action scope.

- Provenance test confirms source refresh, indicator version and calculation run are traceable.

- Regression test confirms previously validated Acholi figures remain unchanged unless an approved methodology version changes them.

- User-facing state distinguishes no data, zero, stale data, data-quality problem and normal performance.

## J.10 Data-quality rules

Each flag has rule ID, severity, evidence, geography/period, timestamps, resolution state and no automatic deletion/correction.

Verification should include both an automated test and an operator-visible check where the component affects the interface or official outputs. The implementation should expose enough metadata to diagnose a failure without reading database rows manually. Any discrepancy between dashboard, API, Excel or PowerPoint is a release blocker until the underlying calculation run and template behaviour are reconciled.

- Functional test covers the expected path and at least one failure/edge path.

- Permission test confirms the feature cannot be used outside the authorised geography/programme/action scope.

- Provenance test confirms source refresh, indicator version and calculation run are traceable.

- Regression test confirms previously validated Acholi figures remain unchanged unless an approved methodology version changes them.

- User-facing state distinguishes no data, zero, stale data, data-quality problem and normal performance.

## J.11 National dashboard

National authorised landing, consistent run across cards/map/table/trends, correct regional drill-down and reproducible exports.

Verification should include both an automated test and an operator-visible check where the component affects the interface or official outputs. The implementation should expose enough metadata to diagnose a failure without reading database rows manually. Any discrepancy between dashboard, API, Excel or PowerPoint is a release blocker until the underlying calculation run and template behaviour are reconciled.

- Functional test covers the expected path and at least one failure/edge path.

- Permission test confirms the feature cannot be used outside the authorised geography/programme/action scope.

- Provenance test confirms source refresh, indicator version and calculation run are traceable.

- Regression test confirms previously validated Acholi figures remain unchanged unless an approved methodology version changes them.

- User-facing state distinguishes no data, zero, stale data, data-quality problem and normal performance.

## J.12 Regional dashboard

District/city peer units, aggregate-from-components logic, map/table consistency, priority calculation and district drill-down.

Verification should include both an automated test and an operator-visible check where the component affects the interface or official outputs. The implementation should expose enough metadata to diagnose a failure without reading database rows manually. Any discrepancy between dashboard, API, Excel or PowerPoint is a release blocker until the underlying calculation run and template behaviour are reconciled.

- Functional test covers the expected path and at least one failure/edge path.

- Permission test confirms the feature cannot be used outside the authorised geography/programme/action scope.

- Provenance test confirms source refresh, indicator version and calculation run are traceable.

- Regression test confirms previously validated Acholi figures remain unchanged unless an approved methodology version changes them.

- User-facing state distinguishes no data, zero, stale data, data-quality problem and normal performance.

## J.13 District facility dashboard

Complete facility list in scope, facility-level table and ranking, data-quality-aware ranking and click-through to facility profile.

Verification should include both an automated test and an operator-visible check where the component affects the interface or official outputs. The implementation should expose enough metadata to diagnose a failure without reading database rows manually. Any discrepancy between dashboard, API, Excel or PowerPoint is a release blocker until the underlying calculation run and template behaviour are reconciled.

- Functional test covers the expected path and at least one failure/edge path.

- Permission test confirms the feature cannot be used outside the authorised geography/programme/action scope.

- Provenance test confirms source refresh, indicator version and calculation run are traceable.

- Regression test confirms previously validated Acholi figures remain unchanged unless an approved methodology version changes them.

- User-facing state distinguishes no data, zero, stale data, data-quality problem and normal performance.

## J.14 Facility dashboard

Population-aware indicators, service-derived measures remain available without population, trends/alerts and scope-correct exports.

Verification should include both an automated test and an operator-visible check where the component affects the interface or official outputs. The implementation should expose enough metadata to diagnose a failure without reading database rows manually. Any discrepancy between dashboard, API, Excel or PowerPoint is a release blocker until the underlying calculation run and template behaviour are reconciled.

- Functional test covers the expected path and at least one failure/edge path.

- Permission test confirms the feature cannot be used outside the authorised geography/programme/action scope.

- Provenance test confirms source refresh, indicator version and calculation run are traceable.

- Regression test confirms previously validated Acholi figures remain unchanged unless an approved methodology version changes them.

- User-facing state distinguishes no data, zero, stale data, data-quality problem and normal performance.

## J.15 ANC module

All agreed formulas/thresholds, inverse teenage pregnancy logic, IFA \>100 flagging, continuum and year comparison.

Verification should include both an automated test and an operator-visible check where the component affects the interface or official outputs. The implementation should expose enough metadata to diagnose a failure without reading database rows manually. Any discrepancy between dashboard, API, Excel or PowerPoint is a release blocker until the underlying calculation run and template behaviour are reconciled.

- Functional test covers the expected path and at least one failure/edge path.

- Permission test confirms the feature cannot be used outside the authorised geography/programme/action scope.

- Provenance test confirms source refresh, indicator version and calculation run are traceable.

- Regression test confirms previously validated Acholi figures remain unchanged unless an approved methodology version changes them.

- User-facing state distinguishes no data, zero, stale data, data-quality problem and normal performance.

## J.16 Intrapartum module

Correct 4.85% expected-delivery denominator, C-section desired range, mortality units, KMC/resuscitation BLUE rules and small-count context.

Verification should include both an automated test and an operator-visible check where the component affects the interface or official outputs. The implementation should expose enough metadata to diagnose a failure without reading database rows manually. Any discrepancy between dashboard, API, Excel or PowerPoint is a release blocker until the underlying calculation run and template behaviour are reconciled.

- Functional test covers the expected path and at least one failure/edge path.

- Permission test confirms the feature cannot be used outside the authorised geography/programme/action scope.

- Provenance test confirms source refresh, indicator version and calculation run are traceable.

- Regression test confirms previously validated Acholi figures remain unchanged unless an approved methodology version changes them.

- User-facing state distinguishes no data, zero, stale data, data-quality problem and normal performance.

## J.17 Immunization module

Correct target coefficients including MV4 4.3%, period scaling, dropout/continuum and no invented programme thresholds.

Verification should include both an automated test and an operator-visible check where the component affects the interface or official outputs. The implementation should expose enough metadata to diagnose a failure without reading database rows manually. Any discrepancy between dashboard, API, Excel or PowerPoint is a release blocker until the underlying calculation run and template behaviour are reconciled.

- Functional test covers the expected path and at least one failure/edge path.

- Permission test confirms the feature cannot be used outside the authorised geography/programme/action scope.

- Provenance test confirms source refresh, indicator version and calculation run are traceable.

- Regression test confirms previously validated Acholi figures remain unchanged unless an approved methodology version changes them.

- User-facing state distinguishes no data, zero, stale data, data-quality problem and normal performance.

## J.18 MPDSR process module

Reported/notified/reviewed counts, COMPLETED-only numerators, ACTIVE counts separate, timeliness methods explicit and maternal/perinatal targets distinct.

Verification should include both an automated test and an operator-visible check where the component affects the interface or official outputs. The implementation should expose enough metadata to diagnose a failure without reading database rows manually. Any discrepancy between dashboard, API, Excel or PowerPoint is a release blocker until the underlying calculation run and template behaviour are reconciled.

- Functional test covers the expected path and at least one failure/edge path.

- Permission test confirms the feature cannot be used outside the authorised geography/programme/action scope.

- Provenance test confirms source refresh, indicator version and calculation run are traceable.

- Regression test confirms previously validated Acholi figures remain unchanged unless an approved methodology version changes them.

- User-facing state distinguishes no data, zero, stale data, data-quality problem and normal performance.

## J.19 MPDSR causes

Perinatal/maternal privacy rules, overlapping cause categories not forced into pie totals, documentation completeness visible and no case-identifying narrative leakage.

Verification should include both an automated test and an operator-visible check where the component affects the interface or official outputs. The implementation should expose enough metadata to diagnose a failure without reading database rows manually. Any discrepancy between dashboard, API, Excel or PowerPoint is a release blocker until the underlying calculation run and template behaviour are reconciled.

- Functional test covers the expected path and at least one failure/edge path.

- Permission test confirms the feature cannot be used outside the authorised geography/programme/action scope.

- Provenance test confirms source refresh, indicator version and calculation run are traceable.

- Regression test confirms previously validated Acholi figures remain unchanged unless an approved methodology version changes them.

- User-facing state distinguishes no data, zero, stale data, data-quality problem and normal performance.

## J.20 Trend engine

Correct period denominator, missing values as gaps, inverse interpretation, target overlays and exportable data.

Verification should include both an automated test and an operator-visible check where the component affects the interface or official outputs. The implementation should expose enough metadata to diagnose a failure without reading database rows manually. Any discrepancy between dashboard, API, Excel or PowerPoint is a release blocker until the underlying calculation run and template behaviour are reconciled.

- Functional test covers the expected path and at least one failure/edge path.

- Permission test confirms the feature cannot be used outside the authorised geography/programme/action scope.

- Provenance test confirms source refresh, indicator version and calculation run are traceable.

- Regression test confirms previously validated Acholi figures remain unchanged unless an approved methodology version changes them.

- User-facing state distinguishes no data, zero, stale data, data-quality problem and normal performance.

## J.21 Contribution/Pareto

Transparent denominator, absolute contribution logic, no misuse as risk ratio and correct child-to-parent reconciliation.

Verification should include both an automated test and an operator-visible check where the component affects the interface or official outputs. The implementation should expose enough metadata to diagnose a failure without reading database rows manually. Any discrepancy between dashboard, API, Excel or PowerPoint is a release blocker until the underlying calculation run and template behaviour are reconciled.

- Functional test covers the expected path and at least one failure/edge path.

- Permission test confirms the feature cannot be used outside the authorised geography/programme/action scope.

- Provenance test confirms source refresh, indicator version and calculation run are traceable.

- Regression test confirms previously validated Acholi figures remain unchanged unless an approved methodology version changes them.

- User-facing state distinguishes no data, zero, stale data, data-quality problem and normal performance.

## J.22 Map engine

Authorised geometries only, correct RAG from indicator rules, drill-down, no-data representation and unmapped units not dropped from other views.

Verification should include both an automated test and an operator-visible check where the component affects the interface or official outputs. The implementation should expose enough metadata to diagnose a failure without reading database rows manually. Any discrepancy between dashboard, API, Excel or PowerPoint is a release blocker until the underlying calculation run and template behaviour are reconciled.

- Functional test covers the expected path and at least one failure/edge path.

- Permission test confirms the feature cannot be used outside the authorised geography/programme/action scope.

- Provenance test confirms source refresh, indicator version and calculation run are traceable.

- Regression test confirms previously validated Acholi figures remain unchanged unless an approved methodology version changes them.

- User-facing state distinguishes no data, zero, stale data, data-quality problem and normal performance.

## J.23 AI Gateway

Provider abstraction, privacy filter, evidence package, cost/usage log, timeouts/fallback and no-AI mode.

Verification should include both an automated test and an operator-visible check where the component affects the interface or official outputs. The implementation should expose enough metadata to diagnose a failure without reading database rows manually. Any discrepancy between dashboard, API, Excel or PowerPoint is a release blocker until the underlying calculation run and template behaviour are reconciled.

- Functional test covers the expected path and at least one failure/edge path.

- Permission test confirms the feature cannot be used outside the authorised geography/programme/action scope.

- Provenance test confirms source refresh, indicator version and calculation run are traceable.

- Regression test confirms previously validated Acholi figures remain unchanged unless an approved methodology version changes them.

- User-facing state distinguishes no data, zero, stale data, data-quality problem and normal performance.

## J.24 Ask the Data

Deterministic authorised evidence retrieval before generation, evidence links, unsupported questions acknowledged and no permission expansion.

Verification should include both an automated test and an operator-visible check where the component affects the interface or official outputs. The implementation should expose enough metadata to diagnose a failure without reading database rows manually. Any discrepancy between dashboard, API, Excel or PowerPoint is a release blocker until the underlying calculation run and template behaviour are reconciled.

- Functional test covers the expected path and at least one failure/edge path.

- Permission test confirms the feature cannot be used outside the authorised geography/programme/action scope.

- Provenance test confirms source refresh, indicator version and calculation run are traceable.

- Regression test confirms previously validated Acholi figures remain unchanged unless an approved methodology version changes them.

- User-facing state distinguishes no data, zero, stale data, data-quality problem and normal performance.

## J.25 Excel export

Screen-matching values/status, calculation sheet, methodology, population/source, raw data where permitted and quality sheet.

Verification should include both an automated test and an operator-visible check where the component affects the interface or official outputs. The implementation should expose enough metadata to diagnose a failure without reading database rows manually. Any discrepancy between dashboard, API, Excel or PowerPoint is a release blocker until the underlying calculation run and template behaviour are reconciled.

- Functional test covers the expected path and at least one failure/edge path.

- Permission test confirms the feature cannot be used outside the authorised geography/programme/action scope.

- Provenance test confirms source refresh, indicator version and calculation run are traceable.

- Regression test confirms previously validated Acholi figures remain unchanged unless an approved methodology version changes them.

- User-facing state distinguishes no data, zero, stale data, data-quality problem and normal performance.

## J.26 PowerPoint export

Approved template version, readable charts/tables, deterministic numbers/colours and AI restricted to designated narrative fields.

Verification should include both an automated test and an operator-visible check where the component affects the interface or official outputs. The implementation should expose enough metadata to diagnose a failure without reading database rows manually. Any discrepancy between dashboard, API, Excel or PowerPoint is a release blocker until the underlying calculation run and template behaviour are reconciled.

- Functional test covers the expected path and at least one failure/edge path.

- Permission test confirms the feature cannot be used outside the authorised geography/programme/action scope.

- Provenance test confirms source refresh, indicator version and calculation run are traceable.

- Regression test confirms previously validated Acholi figures remain unchanged unless an approved methodology version changes them.

- User-facing state distinguishes no data, zero, stale data, data-quality problem and normal performance.

## J.27 Narrative report

Verified evidence and charts, methodology/source/run metadata, privacy controls and no unsupported numerical statements.

Verification should include both an automated test and an operator-visible check where the component affects the interface or official outputs. The implementation should expose enough metadata to diagnose a failure without reading database rows manually. Any discrepancy between dashboard, API, Excel or PowerPoint is a release blocker until the underlying calculation run and template behaviour are reconciled.

- Functional test covers the expected path and at least one failure/edge path.

- Permission test confirms the feature cannot be used outside the authorised geography/programme/action scope.

- Provenance test confirms source refresh, indicator version and calculation run are traceable.

- Regression test confirms previously validated Acholi figures remain unchanged unless an approved methodology version changes them.

- User-facing state distinguishes no data, zero, stale data, data-quality problem and normal performance.

## J.28 Audit log

Material config/security changes recorded with actor/time/before/after and protected from ordinary editing.

Verification should include both an automated test and an operator-visible check where the component affects the interface or official outputs. The implementation should expose enough metadata to diagnose a failure without reading database rows manually. Any discrepancy between dashboard, API, Excel or PowerPoint is a release blocker until the underlying calculation run and template behaviour are reconciled.

- Functional test covers the expected path and at least one failure/edge path.

- Permission test confirms the feature cannot be used outside the authorised geography/programme/action scope.

- Provenance test confirms source refresh, indicator version and calculation run are traceable.

- Regression test confirms previously validated Acholi figures remain unchanged unless an approved methodology version changes them.

- User-facing state distinguishes no data, zero, stale data, data-quality problem and normal performance.

## J.29 Observability

Sync freshness, failures, queues, AI errors/costs, DB performance and safe alerting visible to administrators.

Verification should include both an automated test and an operator-visible check where the component affects the interface or official outputs. The implementation should expose enough metadata to diagnose a failure without reading database rows manually. Any discrepancy between dashboard, API, Excel or PowerPoint is a release blocker until the underlying calculation run and template behaviour are reconciled.

- Functional test covers the expected path and at least one failure/edge path.

- Permission test confirms the feature cannot be used outside the authorised geography/programme/action scope.

- Provenance test confirms source refresh, indicator version and calculation run are traceable.

- Regression test confirms previously validated Acholi figures remain unchanged unless an approved methodology version changes them.

- User-facing state distinguishes no data, zero, stale data, data-quality problem and normal performance.

## J.30 Production deployment

Documented environments, migrations, secrets, backups, rollback, disaster-recovery test and admin/user handoff material.

Verification should include both an automated test and an operator-visible check where the component affects the interface or official outputs. The implementation should expose enough metadata to diagnose a failure without reading database rows manually. Any discrepancy between dashboard, API, Excel or PowerPoint is a release blocker until the underlying calculation run and template behaviour are reconciled.

- Functional test covers the expected path and at least one failure/edge path.

- Permission test confirms the feature cannot be used outside the authorised geography/programme/action scope.

- Provenance test confirms source refresh, indicator version and calculation run are traceable.

- Regression test confirms previously validated Acholi figures remain unchanged unless an approved methodology version changes them.

- User-facing state distinguishes no data, zero, stale data, data-quality problem and normal performance.

# Appendix K. Operational Configuration Checklist Before First National Rollout

Before the first national production release, the following configuration must be loaded and validated. The goal is to prevent a technically complete application from launching with incomplete metadata, populations, permissions or presentation templates.

## Geography and population

- All current regions/sub-regions mapped

- All districts/cities mapped

- All sub-counties imported

- Facilities mapped to correct parent units

- Approved national population file loaded for every required year

- GeoJSON/geometry coverage assessed

- Facility population gaps listed and workflow defined

Completion of this checklist should be evidenced in the release record. Items that are intentionally deferred must have an owner, reason and mitigation; they should not simply remain unknown. Programme owners should sign off formulas/targets, while technical administrators sign off mappings, access and operational readiness.

## DHIS2 metadata

- Production base URL configured securely

- Aggregate data elements mapped

- Program/stage UIDs mapped for MPDSR

- Semantic event fields mapped

- Required data-element access verified with representative user roles

- Analytics-table refresh schedule documented

- Metadata sync and drift alerts enabled

Completion of this checklist should be evidenced in the release record. Items that are intentionally deferred must have an owner, reason and mitigation; they should not simply remain unknown. Programme owners should sign off formulas/targets, while technical administrators sign off mappings, access and operational readiness.

## Indicator configuration

- All ANC formulas entered and versioned

- All intrapartum/newborn formulas entered and versioned

- All immunization coefficients loaded including MV4 4.3%

- Approved EPI targets/bands loaded where available

- Perinatal MPDSR target bands loaded

- Maternal MPDSR target bands loaded

- Methodology text reviewed by programme owners

Completion of this checklist should be evidenced in the release record. Items that are intentionally deferred must have an owner, reason and mitigation; they should not simply remain unknown. Programme owners should sign off formulas/targets, while technical administrators sign off mappings, access and operational readiness.

## Permissions

- National role tested

- Regional role tested

- District role tested

- Facility role tested

- Admin role tested

- Sensitive MPDSR access explicitly separated

- Export and AI permissions tested

Completion of this checklist should be evidenced in the release record. Items that are intentionally deferred must have an owner, reason and mitigation; they should not simply remain unknown. Programme owners should sign off formulas/targets, while technical administrators sign off mappings, access and operational readiness.

## Publishing

- Excel template approved

- National PowerPoint template approved

- Regional PowerPoint template approved

- District/facility template approved

- MPDSR template approved

- Narrative report template approved

- Template versioning and preview working

Completion of this checklist should be evidenced in the release record. Items that are intentionally deferred must have an owner, reason and mitigation; they should not simply remain unknown. Programme owners should sign off formulas/targets, while technical administrators sign off mappings, access and operational readiness.

## AI

- Primary low-cost provider configured

- Fallback provider optional/confirmed

- Sensitive-data policy applied

- Token/cost limits set

- Evidence validation enabled

- No-AI deterministic fallback tested

Completion of this checklist should be evidenced in the release record. Items that are intentionally deferred must have an owner, reason and mitigation; they should not simply remain unknown. Programme owners should sign off formulas/targets, while technical administrators sign off mappings, access and operational readiness.

## Operations

- Backups configured

- Restore tested

- DHIS2 sync schedule active

- System-health monitoring active

- Job queues monitored

- Admin runbook complete

- User onboarding guide complete

- Regression suite green

Completion of this checklist should be evidenced in the release record. Items that are intentionally deferred must have an owner, reason and mitigation; they should not simply remain unknown. Programme owners should sign off formulas/targets, while technical administrators sign off mappings, access and operational readiness.

# Appendix L. Ultimate IDE Context Addendum - Latest Decisions After the Detailed Blueprint

This appendix captures the latest decisions, corrections, examples, analytical fixtures, implementation guardrails, and product intent that must be carried forward alongside the main blueprint. Where this appendix conflicts with an older illustrative mock-up, earlier narrative, or older calculation example, this appendix and the latest explicit rule in the main blueprint take precedence. The IDE must never resolve a conflict by guessing silently.

## L.1 Source-of-truth and conflict-resolution hierarchy

The project contains several kinds of information. They are not all equal. The IDE must apply this precedence order whenever two artifacts appear inconsistent:

1. **Latest explicit user decision recorded in this handoff.** These are binding product decisions unless later changed explicitly.
2. **Latest agreed methodology specification for an indicator or module.** Formula, denominator, threshold, colour and aggregation rules are contractual.
3. **Verified analytical regression fixtures.** These are expected outputs used to test the deterministic calculation engine.
4. **Source data retrieved from authorised DHIS2 APIs or approved uploaded data files.** These provide numerators, denominators and event records.
5. **UI mock-up content.** Mock-ups are authoritative for layout, interaction and visual style, but most numbers displayed in generated images are illustrative unless separately marked as verified fixtures.
6. **Older prompts, slide drafts and historical analyses.** They are useful context but must not override a later agreed method.

The system must represent unresolved items explicitly as configuration or TODOs. It must not fabricate a target, data-element UID, population, facility coordinate, denominator or clinical interpretation.

## L.2 One-sentence product definition

The Uganda Health Performance Intelligence Platform is a national, role-based analytical layer above DHIS2 that converts authorised routine aggregate and event data into deterministic health indicators, drill-down scorecards, maps, trends, data-quality diagnostics, AI-supported interpretation, and publication-ready Excel, PowerPoint and narrative reports from the highest organisational level a user is authorised to access down to individual health facilities.

## L.3 What the product is not

The platform is not intended to replace DHIS2 as Uganda's routine health information system. It is not a second clinical record system. It is not a free-form LLM that invents formulas. It is not a collection of disconnected dashboards built programme by programme. It is not a national-only dashboard. It is not an MNCH-only architecture even though MNCH is the first production module. It is not a static presentation generator. It is an extensible health-performance intelligence layer with deterministic calculations and a reusable geography, permissions, data-quality, analytics and publishing architecture.

## L.4 Current release scope versus future scope

The first serious production release is **MNCH v1**. The visible navigation and screen design for this release should focus on the programme areas already worked through in detail:

- Overview
- MNCH, with ANC, intrapartum and newborn analytical workspaces
- Immunization / EPI, including malaria vaccination and child-health interventions
- MPDSR
- Maps
- Trends
- Reports
- Exports
- AI Insights / Ask the Data
- Admin, visible only when authorised

Do not clutter the initial MNCH mock-ups with standalone HIV, TB, general malaria or WASH navigation. Those are future programme modules. The architecture must support them, but the first user experience should remain focused. Malaria vaccination belongs in Immunization/EPI for this release. IPT3 belongs in ANC/malaria-in-pregnancy analysis. A future full Malaria module will be separate.

## L.5 Historical platform context that may be reusable, but is not automatically binding

Earlier work produced a Uganda Health Analytics Platform based on Python 3.12 and Flask, connected to Uganda's DHIS2 HMIS APIs, with broad district/facility coverage, authentication, caching, pooling, rate limiting and export functions. Earlier modules included EPI/immunization, maternal health, malaria surveillance, WASH and HMIS reporting. This experience is useful because it proves the user is comfortable with Flask/Python and DHIS2 integration and has already encountered real-world deployment and metadata issues.

However, the new Health Performance Intelligence Platform should not inherit legacy constraints accidentally. Reuse proven connector code, data models or deployment patterns only after validating that they fit the new permission model, indicator registry, event analytics, UI architecture and reproducibility requirements.

A specific deployment lesson from prior work is worth preserving: runtime applications should use a least-privilege database role and pooled connection, while migration/owner privileges should be separated. Do not expose database-owner credentials to the web runtime.

# Appendix M. National Geography, Authorised Landing and Drill-Down Contract

## M.1 Highest-authorised-level landing rule

The default landing page is not always national. It is the highest organisational level the authenticated user is authorised to analyse.

- A national analyst lands on **Uganda**.
- A regional or sub-regional analyst lands on the authorised region or sub-region.
- A district analyst lands on the authorised district or city.
- A sub-county user lands on the authorised sub-county.
- A facility-only user lands directly on the facility performance profile.

The system must never show an inaccessible national overview merely as a shell. The first screen must immediately reflect the user's real analytical scope.

## M.2 Three permission dimensions

Every access decision is the intersection of three dimensions:

### Geography permission
Determines the organisational units the user may query. A district user must not obtain sibling district data by editing a URL, API payload or front-end state. Descendant access is allowed only inside the assigned boundary.

### Programme permission
Determines which modules and indicator groups the user can view. A user may have access to Pader District but only the MNCH programme, while another user may have access to the same geography and several programmes.

### Action permission
Determines what the user can do: view, compare, export Excel, export PowerPoint, generate AI reports, edit facility population, upload GeoJSON, resolve a data-quality issue, edit indicator definitions, manage DHIS2 mappings, manage users or configure AI providers.

All three dimensions must be enforced server-side. Hiding buttons in the UI is not sufficient security.

## M.3 Geography hierarchy

The minimum analytical hierarchy is:

**Uganda -> Region/Sub-region -> District/City -> Sub-county -> Health Facility**

The geography master must allow both official hierarchical parents and optional analytical groupings such as sub-regions or referral catchments. A grouping must never duplicate or alter raw DHIS2 organisational units; it is a mapped analytical layer.

## M.4 Dynamic row grain

The scorecard row grain must change with the selected scope.

- Uganda selected -> rows are regions/sub-regions according to configured national analytical grouping.
- Region/sub-region selected -> rows are districts/cities.
- District selected -> rows may be sub-counties or facilities, controlled by a view switch.
- Sub-county selected -> rows are facilities.
- Facility selected -> no lower geography table is required; show an indicator profile, trends, numerator/denominator lineage and alerts.

## M.5 District facility-performance screen is mandatory

A specific screen must exist for a district analyst who wants to compare facilities. This screen was initially missing from the visual set and was later explicitly required. It should preserve the same visual language as the national and regional views.

Recommended components:

1. Scope header showing district, period and comparison period.
2. District-level KPI cards.
3. Main facility-performance scorecard with facility name, facility level and selected indicators.
4. RAG/BLUE colour coding in the same style as regional scorecards.
5. Key insights explaining facilities driving district strengths, gaps and data-quality issues.
6. Facility performance trends.
7. Top/bottom facility ranking for the selected indicator.
8. Downloads for Excel, PowerPoint and report.
9. Click-through to an individual facility profile.

The screenshot created for this concept used Pader District as an example, but the actual implementation must work for any authorised district and use real configured facilities.

# Appendix N. Population and Denominator Rules - Consolidated Master Specification

## N.1 Population master

The user intends to provide population estimates for the whole country, including sub-county populations and projections. The platform must store population by geography and year with explicit provenance.

Minimum fields:

- org_unit_id
- year
- population
- source_name
- source_document_or_dataset
- population_type: census, projection, approved local estimate, facility catchment estimate
- version
- valid_from / valid_to where appropriate
- imported_at
- imported_by
- approval status
- notes

Never overwrite an old population silently. New projections or corrections create a new version.

## N.2 Financial-year population convention currently agreed for MNCH

For the analyses worked through in this project, the population year follows the year in which the financial year begins:

- FY2024/25 -> use 2024 population
- FY2025/26 -> use 2025 population

The rule should be implemented as configurable period-to-population resolution, not hard-coded only for these two years. If the programme later adopts a different convention, the indicator version must preserve historical reproducibility.

## N.3 Facility catchment populations

UBOS does not necessarily provide official catchment populations for every facility. If a population-based indicator is requested at facility level and the platform has no approved facility catchment population, the UI should ask the authorised user to enter or upload the facility population before calculating that indicator.

The prompt should be contextual and should appear only when needed. For example, ANC1 coverage requires a population denominator, while Hb testing at ANC1 does not. Once an approved facility population is entered, it should be stored with year, source, user and timestamp so the user is not prompted repeatedly.

Historical analysis in Pader used a possible allocation approach based on facility new attendance divided by total attendance multiplied by district population. This may be offered later as an optional assisted-estimation tool, but it must **not** be the default automatic facility population method unless explicitly approved. User-entered or officially supplied catchment populations take precedence.

## N.4 Period adjustment for annual target populations

Where a target population coefficient is annual, the denominator must be adjusted for the analysis period.

For `m` months in the period:

`period_target = annual_population * target_coefficient * (m / 12)`

Examples:

- Full financial year: multiply by 12/12.
- Quarter: multiply by 3/12.
- One month: multiply by 1/12.

The period engine should calculate the exact number of months or use a programme-specific denominator rule. It must never assume every query is a full year.

## N.5 Known Acholi population regression fixture

These population values were used in the verified FY2024/25 versus FY2025/26 comparisons and should remain available as non-production regression fixtures.

| Geography | 2024 Census | 2025 Projection |
|---|---:|---:|
| Agago | 307,235 | 314,700 |
| Amuru | 247,574 | 261,130 |
| Gulu City | 233,271 | 247,560 |
| Gulu District | 135,373 | 142,280 |
| Kitgum | 239,655 | 242,410 |
| Lamwo | 213,156 | 227,180 |
| Nwoya | 220,593 | 242,910 |
| Omoro | 207,339 | 225,620 |
| Pader | 240,159 | 248,910 |
| **Acholi** | **2,044,355** | **2,152,700** |

The Acholi aggregate is the sum of the constituent units in the fixture. Production population values must come from the approved national population master supplied to the system.

# Appendix O. Complete MNCH Indicator Logic - Latest Agreed Rules

This appendix is a compact but explicit machine-oriented restatement of the indicator logic. The main blueprint and methodology snapshots provide additional narrative context.

## O.1 Universal calculation rules

1. Aggregate raw numerators and denominators before computing a parent geography percentage or rate.
2. Never average district or facility percentages to obtain a region or district value unless an indicator definition explicitly says to average.
3. Keep calculation precision internally. Round only at the display/output layer.
4. Use percentage points, not percent change, when describing differences between percentage indicators unless the user explicitly requests relative change.
5. Use the indicator's rate unit when describing changes in PMR, stillbirth rate or MMR.
6. For inverse indicators, a decrease is improvement. For higher-is-better indicators, an increase is generally improvement. For range indicators such as C-section rate, movement must be interpreted relative to the desired range.
7. Do not cap values silently.
8. Distinguish expected-population coverage from bounded subset proportions. Expected-population coverage can plausibly exceed 100% because of catchment movement or denominator estimation. A bounded subset proportion such as successful resuscitation cannot logically exceed 100% and should be BLUE/data-quality flagged.
9. BLUE is not a good-performance state. It means the value should not be interpreted normally until the data issue is resolved.
10. `N/A`, `No denominator`, `No cases`, `Missing`, and numeric zero are distinct states.

## O.2 ANC indicators

### ANC1 coverage

`ANC1 / (population * 0.05) * 100`

- Denominator type: expected pregnancies
- Target: 95%
- Green: >=95%
- Yellow: 75.0-94.9%
- Red: <75%
- Direction: higher is better
- Values above 100% remain visible and are not automatically BLUE because the denominator is estimated population.

### ANC first trimester

`ANC1_first_trimester / ANC1 * 100`

- Target: 45%
- Green: >=45%
- Yellow: 30.0-44.9%
- Red: <30%
- Direction: higher is better

### ANC4 coverage

`ANC4 / (population * 0.05) * 100`

- Target: 75%
- Green: >=75%
- Yellow: 50.0-74.9%
- Red: <50%
- Direction: higher is better

### ANC8 coverage

`ANC8 / (population * 0.05) * 100`

- Target: 15%
- Green: >=15%
- Yellow: 7.0-14.9%
- Red: <7%
- Direction: higher is better

### IPT3 coverage

`IPT3 / (population * 0.05) * 100`

- Target: 75%
- Green: >=75%
- Yellow: 50.0-74.9%
- Red: <50%
- Direction: higher is better
- Programme interpretation: ANC and malaria-in-pregnancy prevention.

### Hb testing at ANC1

`Hb_tested / ANC1 * 100`

- Target: 75%
- Green: >=75%
- Yellow: 50.0-74.9%
- Red: <50%
- Denominator is ANC1, not population.

### Iron and folic acid at ANC1

`IFA_30_or_more / ANC1 * 100`

- Target: 95%
- Green: >=95%
- Yellow: 75.0-94.9%
- Red: <75%
- Do not relabel simply as FeSO4; programme term is Iron and Folic Acid supplementation.
- If values exceed 100%, retain them and flag for interpretation. The exact BLUE treatment should depend on whether the numerator is confirmed as a bounded unique-client subset or a routine service count that can include repeat supplementation. Current Acholi comparison treated extreme >100% IFA as a data-definition/reporting issue.

### Obstetric ultrasound during ANC

`obstetric_ultrasound / ANC1 * 100`

- Target: 75%
- Green: >=75%
- Yellow: 50.0-74.9%
- Red: <50%
- The final agreed denominator is ANC1, not total ANC attendances.

### Teenage pregnancy among ANC1 attendees

`(ANC1_age_under_15 + ANC1_age_15_19) / ANC1 * 100`

- Direction: lower is better
- Green: <5%
- Yellow: 5.0-12.9%
- Red: >=13%
- Never apply higher-is-better logic to this indicator.

## O.3 Intrapartum and newborn indicators

### Institutional delivery coverage

`total_deliveries / (population * 0.0485) * 100`

- Target: 65%
- Green: >=65%
- Yellow: 50.0-64.9%
- Red: <50%
- Values above 100% are not automatically impossible because expected deliveries are estimated.

### Caesarean section rate

`caesarean_sections / total_deliveries * 100`

- Desired range: 5.0-15.0%
- Green: 5.0-15.0%
- Yellow low: 3.0-4.9%
- Yellow high: 15.1-20.0%
- Red low: <3.0%
- Red high: >20.0%
- Blue: >100%
- Direction: desired range, not monotonic.

### Low-birth-weight babies initiated on KMC

Use the supplied KMC percentage directly unless raw eligible LBW and KMC counts are later available and an explicit formula version is approved.

- Target: >=95%
- Green: 95.0-100.0%
- Yellow: 75.0-94.9%
- Red: <75%
- Blue: >100%

### Successful resuscitation of birth asphyxia

`successfully_resuscitated / birth_asphyxia_cases * 100`

- Green: 90.0-100.0%
- Yellow: 70.0-89.9%
- Red: <70%
- Blue: >100%
- If denominator is zero, return N/A/no asphyxia cases; never divide by zero.

### Perinatal mortality rate

`(fresh_stillbirths + macerated_stillbirths + newborn_deaths) / total_deliveries * 1000`

- Unit: per 1,000 total births/deliveries under the agreed operational definition
- Green: <=12
- Yellow: >12 to 20
- Red: >20
- Direction: lower is better
- Do not display `%`.

### Fresh stillbirth rate

`fresh_stillbirths / total_deliveries * 1000`

- Unit: per 1,000 deliveries
- Green: <=5
- Yellow: >5 to 10
- Red: >10
- Direction: lower is better
- Interpretation: potential intrapartum quality signal; routine data alone do not prove causation.

### Maternal mortality ratio

`maternal_deaths / live_births * 100000`

- Unit: maternal deaths per 100,000 live births
- Green: <=183
- Yellow: 184-300
- Red: >300
- Direction: lower is better
- Always consider the underlying count because small district counts can produce unstable ratios.

## O.4 Immunization and child-health denominator coefficients

The EPI methodology states that performance is calculated as doses administered divided by the target population for the selected period. The annual target population is population multiplied by the programme coefficient, then adjusted to the selected number of months.

| Vaccine / intervention | Age / programme group | Annual target coefficient |
|---|---|---:|
| BCG | At birth | 4.85% |
| OPV0 | At birth | 4.85% |
| Hepatitis B birth dose | At birth | 4.85% |
| OPV1 | 6 weeks | 4.3% |
| DPT-HepB-Hib1 | 6 weeks | 4.3% |
| RotaV1 | 6 weeks | 4.3% |
| PCV1 | 6 weeks | 4.3% |
| IPV1 | 6 weeks | 4.3% |
| OPV2 | 10 weeks | 4.3% |
| DPT-HepB-Hib2 | 10 weeks | 4.3% |
| PCV2 | 10 weeks | 4.3% |
| RotaV2 | 10 weeks | 4.3% |
| OPV3 | 14 weeks | 4.3% |
| DPT-HepB-Hib3 | 14 weeks | 4.3% |
| PCV3 | 14 weeks | 4.3% |
| IPV2 | 14 weeks | 4.3% |
| Malaria vaccine dose 1 | 6 months | 4.3% |
| Malaria vaccine dose 2 | 7 months | 4.3% |
| Malaria vaccine dose 3 | 8 months | 4.3% |
| **Malaria vaccine dose 4** | later scheduled dose | **4.3%** |
| Measles-Rubella | 9 months | 4.3% |
| Yellow fever | 9 months | 4.3% |
| Td, women of childbearing age | 15-49 years | 23% |
| HPV vaccination | target girls | 1.53% |
| Vitamin A 100,000 IU | 6-11 months | 1.93% |
| Vitamin A 200,000 IU / deworming | 12-59 months | 16.2% |
| Deworming | 1-14 years | 49.3% |
| Under-five population | under 5 | 20.5% |

**Explicit correction:** Malaria vaccine dose 4 uses the same **4.3%** annual target coefficient as malaria vaccine doses 1-3.

### Generic EPI coverage formula

`coverage = doses_administered / (population * target_coefficient * period_fraction) * 100`

where `period_fraction = months_in_period / 12` for standard monthly/quarterly/full-year analyses.

### Dropout analytics

The platform should support configurable dropout indicators, including:

`DPT1_DPT3_dropout = (DPT1 - DPT3) / DPT1 * 100`

`DPT1_MR1_dropout = (DPT1 - MR1) / DPT1 * 100`

`MV1_MV4_dropout = (MV1 - MV4) / MV1 * 100`

If the entry dose denominator is zero, return N/A rather than a fabricated percentage.

# Appendix P. MPDSR Master Specification - Perinatal and Maternal Notification and Review

## P.1 Core principle

Every reported perinatal and maternal death is expected to enter the notification and review process. The scorecard must compare routine aggregate reported deaths against completed line-list events and timing. The platform must also preserve unfinished ACTIVE events and data-quality/reconciliation problems rather than hiding them.

## P.2 Perinatal process target and colours

For perinatal death notification and review process indicators:

- Target: >=90%
- Green: 90.0-100.0%
- Yellow: 75.0-89.9%
- Red: <75.0%
- Blue: >100%, N/A, or clear reconciliation/data-quality issue

Apply to:

- proportion notified
- proportion notified on time
- proportion reviewed
- proportion reviewed on time

Count columns remain neutral.

## P.3 Maternal process target and colours

For maternal death notification and review process indicators:

- Target: 100%
- Green: 100%
- Yellow: 90.0-99.9%
- Red: <90%
- Blue: >100%, N/A, or clear data-quality/non-assessable state

Count columns remain neutral. Because maternal counts are small, display counts alongside percentages wherever practical.

## P.4 Notification timeliness

The notification exports analysed during design contained notification dates without reliable time-of-day information. Therefore the current operational proxy for <=24-hour notification is:

**notification on the same calendar day as death or on the next calendar day**.

This limitation must be visible in methodology/help text. If future DHIS2 data expose exact notification timestamps, the indicator version can switch to exact elapsed-hours logic after validation.

Records with unusable death dates are not automatically late. Their timeliness state is `NOT_ASSESSABLE` and may be displayed BLUE/N/A depending on the scorecard.

## P.5 Review timeliness

A completed review is on time when the verified review event date occurs between 0 and 7 calendar days after the recorded date of death, inclusive. A review date earlier than the death date is a data-quality error, not a timely review.

For maternal reviews, the source export used during development labelled the review-stage event date as `Date of notification`. The final production connector must map the actual DHIS2 program-stage semantics and confirm the correct event/review date through metadata rather than trusting an ambiguous spreadsheet column label.

## P.6 Event status

Only `COMPLETED` events count in completed notification/review numerators. `ACTIVE` events must remain visible as `Active (not completed)` and should feed worklist/action views.

## P.7 Case linkage

The uploaded notification and review line lists used during manual analysis did not expose a clearly shared unique identifier for deterministic one-to-one linkage across every stage. Therefore prior presentation logic compared aggregate stage counts and did not claim a literal case-level funnel.

The production platform should use a shared MPDSR case/event identifier whenever DHIS2 metadata makes one available. If a unique linkage cannot be guaranteed, the UI must use parallel process bars/tables rather than a case-level funnel and must label the limitation.

# Appendix Q. Verified MPDSR Regression Fixtures

These figures were independently checked during the analytical work and are valuable as automated regression fixtures. They are not a substitute for production DHIS2 data.

## Q.1 FY2025/26 reported mortality totals

- Fresh stillbirths: 420
- Macerated stillbirths: 464
- Newborn deaths: 557
- Total perinatal deaths: 1,441
- Maternal deaths: 56

Perinatal deaths are defined as `420 + 464 + 557 = 1,441`.

## Q.2 Monthly Acholi reported mortality counts

| Month | Fresh SB | Macerated SB | Newborn deaths | Perinatal deaths | Maternal deaths |
|---|---:|---:|---:|---:|---:|
| Jul-25 | 32 | 28 | 34 | 94 | 4 |
| Aug-25 | 64 | 39 | 43 | 146 | 5 |
| Sep-25 | 39 | 47 | 46 | 132 | 5 |
| Oct-25 | 38 | 47 | 49 | 134 | 4 |
| Nov-25 | 32 | 37 | 47 | 116 | 5 |
| Dec-25 | 38 | 49 | 50 | 137 | 4 |
| Jan-26 | 38 | 53 | 50 | 141 | 6 |
| Feb-26 | 29 | 24 | 40 | 93 | 2 |
| Mar-26 | 33 | 35 | 46 | 114 | 3 |
| Apr-26 | 18 | 35 | 56 | 109 | 7 |
| May-26 | 23 | 32 | 50 | 105 | 7 |
| Jun-26 | 36 | 38 | 46 | 120 | 4 |
| **Annual** | **420** | **464** | **557** | **1,441** | **56** |

## Q.3 Quarterly mortality composition

Financial-year quarters:

- Q1 = Jul-Sep
- Q2 = Oct-Dec
- Q3 = Jan-Mar
- Q4 = Apr-Jun

| Quarter | Fresh SB | Macerated SB | Newborn deaths | Perinatal deaths | Maternal deaths |
|---|---:|---:|---:|---:|---:|
| Q1 | 135 | 114 | 123 | 372 | 14 |
| Q2 | 108 | 133 | 146 | 387 | 13 |
| Q3 | 100 | 112 | 136 | 348 | 11 |
| Q4 | 77 | 105 | 152 | 334 | 18 |

Newborn-death share of perinatal deaths:

- Q1: 33.1%
- Q2: 37.7%
- Q3: 39.1%
- Q4: 45.5%

Fresh-stillbirth share:

- Q1: 36.3%
- Q2: 27.9%
- Q3: 28.7%
- Q4: 23.1%

Interpretation rule: the composition of reported perinatal deaths shifted toward newborn deaths later in the FY. Do not infer the cause of that shift from counts alone.

## Q.4 District annual mortality and service-volume fixture

| District | Deliveries | Fresh SB | Macerated SB | Newborn deaths | Perinatal deaths | Maternal deaths |
|---|---:|---:|---:|---:|---:|---:|
| Agago | 9,501 | 44 | 55 | 66 | 165 | 2 |
| Amuru | 7,281 | 22 | 27 | 10 | 59 | 2 |
| Gulu City | 15,960 | 178 | 166 | 279 | 623 | 33 |
| Gulu District | 3,365 | 11 | 10 | 13 | 34 | 1 |
| Kitgum | 9,068 | 64 | 77 | 78 | 219 | 6 |
| Lamwo | 6,442 | 15 | 27 | 21 | 63 | 2 |
| Nwoya | 6,791 | 41 | 43 | 39 | 123 | 5 |
| Omoro | 6,042 | 21 | 33 | 28 | 82 | 3 |
| Pader | 6,148 | 24 | 26 | 23 | 73 | 2 |
| **Acholi** | **70,598** | **420** | **464** | **557** | **1,441** | **56** |

## Q.5 Burden-concentration fixture

Approximate district shares used in the analytical hotspot view:

| District | Share of deliveries | Share of perinatal deaths | Share of maternal deaths |
|---|---:|---:|---:|
| Agago | 13.5% | 11.5% | 3.6% |
| Amuru | 10.3% | 4.1% | 3.6% |
| Gulu City | 22.6% | 43.2% | 58.9% |
| Gulu District | 4.8% | 2.4% | 1.8% |
| Kitgum | 12.8% | 15.2% | 10.7% |
| Lamwo | 9.1% | 4.4% | 3.6% |
| Nwoya | 9.6% | 8.5% | 8.9% |
| Omoro | 8.6% | 5.7% | 5.4% |
| Pader | 8.7% | 5.1% | 3.6% |

Do not call share ratios risk ratios. Gulu City's 43.2% perinatal-death share relative to a 22.6% delivery share is a descriptive concentration signal, not evidence that an individual patient is 1.9 times more likely to die.

## Q.6 Perinatal notification/review scorecard fixture

| District | Reported | Notified | % Notified | % Notified on time | Reviewed | % Reviewed | % Reviewed on time |
|---|---:|---:|---:|---:|---:|---:|---:|
| Agago | 165 | 155 | 93.9% | 87.9% | 137 | 83.0% | 71.5% |
| Amuru | 59 | 49 | 83.1% | 67.8% | 55 | 93.2% | 64.4% |
| Gulu City | 623 | 380 | 61.0% | 49.1% | 402 | 64.5% | 44.6% |
| Gulu District | 34 | 31 | 91.2% | 82.4% | 29 | 85.3% | 58.8% |
| Kitgum | 219 | 177 | 80.8% | 63.0% | 142 | 64.8% | 44.3% |
| Lamwo | 63 | 63 | 100.0% | 77.8% | 55 | 87.3% | 77.8% |
| Nwoya | 123 | 115 | 93.5% | 89.4% | 106 | 86.2% | 78.0% |
| Omoro | 82 | 75 | 91.5% | 63.4% | 62 | 75.6% | 28.0% |
| Pader | 73 | 80 | 109.6% | 86.3% | 76 | 104.1% | 64.4% |
| **Acholi** | **1,441** | **1,125** | **78.1%** | **64.6%** | **1,064** | **73.8%** | **53.2%** |

Pader's >100% values are expected regression tests for BLUE/reconciliation logic. They must not be capped or coloured green.

## Q.7 Perinatal quarterly process fixture

| Quarter | Notification coverage | Timely notification | Review coverage | Timely review |
|---|---:|---:|---:|---:|
| Q1 Jul-Sep | 57.5% | 50.5% | 58.1% | 43.0% |
| Q2 Oct-Dec | 82.4% | 64.1% | 70.0% | 48.1% |
| Q3 Jan-Mar | 90.5% | 75.3% | 87.1% | 58.9% |
| Q4 Apr-Jun | 82.9% | 69.8% | 82.0% | 64.4% |

The quarterly chart should show month ranges beneath the quarter labels and a 90% target line.

## Q.8 August pressure-point fixture

August 2025 had 146 reported perinatal deaths, the highest monthly total in the FY. In the prior line-list analysis:

- completed notifications: 70 = 47.9%
- verifiable timely notifications: 60 = 41.1%
- completed reviews: 64 = 43.8%
- reviewed within seven days: 45 = 30.8%

This is a high-workload review signal, not proof that workload caused the process gap.

## Q.9 Active event and date-quality fixture

Perinatal events in the analysed FY cohort:

- active notification events: 28
- active review events: 62
- completed notification records with notification date before death date: 27
- completed review records with review calendar date before death date: 35

Facility concentrations identified in the line-list review included:

- Gulu Regional Referral Hospital: 26 active review events and 13 active notification events
- Anaka General Hospital: 12 active review events
- St. Mary's Hospital Lacor: 5 active review events
- St. Joseph's Kitgum Hospital: 4 active review events

For date-quality issues, notable facility counts included Kitgum General Hospital, St. Mary's Hospital Lacor, Gulu Regional Referral Hospital and several other facilities. These counts are quality-improvement signals, not claims about clinical quality.

# Appendix R. Perinatal Cause and Documentation Deep-Dive Fixture

## R.1 Completed review cohort

The analysed FY cohort contained 1,064 completed perinatal death reviews. The detailed cause analysis must recognise that cause fields may overlap and that some records have no populated cause field.

### Cause-field completeness

- No probable-cause field populated: 318 = 29.9%
- Exactly one cause field: 576 = 54.1%
- Two or more cause fields: 170 = 16.0%

Because causes can overlap, do not use a pie chart for cause categories.

### Deterioration in cause documentation by quarter

Proportion of completed reviews with no probable-cause field populated:

- Q1: 22.2%
- Q2: 25.5%
- Q3: 30.7%
- Q4: 39.4%

This is a strong quality-of-review signal: timeliness improved over the year while cause documentation became less complete.

## R.2 Neonatal death review cause mentions

Cohort: 433 completed neonatal-death reviews.

- Birth asphyxia: 159 = 36.7%
- Prematurity complications: 79 = 18.2%
- Septicaemia: 47 = 10.9%
- Congenital anomalies: 32 = 7.4%
- Birth trauma: 25 = 5.8%
- Unknown: approximately 10 = 2.3% in the later presentation fixture
- Other/free text: approximately 100 = 23.1% in the later presentation fixture

Primary narrative: birth asphyxia is the dominant structured probable-cause signal among reviewed neonatal deaths, followed by prematurity and sepsis.

## R.3 Fresh stillbirth review cause mentions

Cohort: 275 completed fresh-stillbirth reviews.

- Other/free text: 116 = 42.2%
- Birth asphyxia: 61 = 22.2%
- Prematurity: 14 = 5.1%
- Unknown: 14 = 5.1%

Primary narrative: heavy use of `Other` reduces specificity; birth asphyxia is the largest named structured signal.

## R.4 Macerated stillbirth review cause mentions

Cohort: 330 completed macerated-stillbirth reviews.

- Other/free text: 140 = 42.4%
- Unknown: 41 = 12.4%
- Birth asphyxia: 20 = 6.1%
- Congenital anomalies: 17 = 5.2%
- Septicaemia: 15 = 4.5%

Primary narrative: cause specificity is weaker for macerated stillbirth reviews, with high use of `Other` and `Unknown`.

## R.5 The `Other` field

A later deep dive identified 363 completed FY reviews with an `Other` cause entry. Free-text themes were screened and grouped for analytical learning. The thematic counts may overlap and are not official mutually exclusive causes.

Recurring themes included approximately:

- hypoxia / asphyxia / fetal distress: 87 mentions
- placental / APH / abruption problems: 52
- cord complications: 44
- maternal malaria: 42
- infection / sepsis / chorioamnionitis: 35
- prematurity / RDS / low birth weight: 30
- hypertensive disorders: 25
- congenital anomalies: 13

At least 58 `Other` entries, about 16.0% of the 363, appeared to contain language that could fit an existing structured cause field such as birth asphyxia/HIE, neonatal sepsis, prematurity/RDS or congenital anomalies. The correct system behaviour is to flag this as possible coding inconsistency for review, not to automatically recode historical records without approval.

## R.6 Facility-specific documentation signals

Facility-level documentation findings can be used in data-quality follow-up because they describe record completeness/coding, not individual mortality blame.

High use of `Other` in the analysed completed reviews included:

- Dr. Ambrosoli Memorial Hospital Kalongo: 78 of 101 = 77.2%
- Pajule HC IV: 20 of 34 = 58.8%
- St. Mary's Hospital Lacor: 93 of 250 = 37.2%
- Anaka General Hospital: 33 of 96 = 34.4%

No probable-cause field populated included:

- Gulu Regional Referral Hospital: 112 of 151 = 74.2%
- Kitgum General Hospital: 29 of 66 = 43.9%
- Namokora HC IV: 13 of 31 = 41.9%
- Anaka General Hospital: 26 of 96 = 27.1%

The dashboard should make these actionable through a Data Quality workspace or facility drill-down. It must not frame them as a league table of clinical quality.

# Appendix S. Maternal MPDSR Deep-Dive Fixture and Privacy Contract

Maternal death analysis is expected to be rich and useful because stakeholders need to understand what happened. At the same time, the data are sensitive and small-number disclosure risk is real. The platform must therefore distinguish **analytical depth** from **case exposure**.

## S.1 Maternal scorecard regression fixture

| District | Reported | Notified | % Notified | % Notified on time | Completed reviewed | % Reviewed | % Reviewed on time |
|---|---:|---:|---:|---:|---:|---:|---:|
| Agago | 2 | 2 | 100.0% | 50.0% | 2 | 100.0% | 100.0% |
| Amuru | 2 | 1 | 50.0% | 0.0% | 2 | 100.0% | 50.0% |
| Gulu City | 33 | 30 | 90.9% | 63.6% | 32 | 97.0% | 72.7% |
| Gulu District | 1 | 1 | 100.0% | N/A | 1 | 100.0% | 100.0% |
| Kitgum | 6 | 6 | 100.0% | 66.7% | 6 | 100.0% | 83.3% |
| Lamwo | 2 | 2 | 100.0% | 100.0% | 2 | 100.0% | 100.0% |
| Nwoya | 5 | 5 | 100.0% | 80.0% | 3 | 60.0% | 60.0% |
| Omoro | 3 | 3 | 100.0% | 100.0% | 3 | 100.0% | 100.0% |
| Pader | 2 | 2 | 100.0% | 100.0% | 2 | 100.0% | 100.0% |
| **Acholi** | **56** | **52** | **92.9%** | **66.1%** | **53** | **94.6%** | **76.8%** |

Gulu District notification timeliness is N/A because the analysed death-date field did not permit reliable timing. This should be BLUE/non-assessable rather than red/late.

Two maternal notification records in the source analysis had unusable/incomplete death-date information. The system must never infer that such records were late; it should record `timeliness_assessable = false`.

## S.2 Maternal workflow counts

- reported maternal deaths: 56
- notification records: 52 = 92.9%
- assessable notification records: 50
- same-day notifications: 26
- next-calendar-day notifications: 11
- same/next-day notifications: 37 = 74.0% of assessable notifications and 66.1% of all reported deaths
- completed reviews: 53 = 94.6%
- active reviews: 3 = 5.4%
- completed reviews within seven days: 43 = 81.1% of completed reviews and 76.8% of reported deaths

The later final slide language intentionally removed the word `provisional` from the seven-day presentation metric. The production system, however, must map the actual DHIS2 review-stage event date correctly through metadata so the calculation is semantically sound.

## S.3 Active maternal reviews

In the later review of the uploaded line list, three active maternal review events were identified. A final slide prompt attributed these to:

- Anaka General Hospital: 2
- Gulu Military General Hospital: 1

The production system should always derive such facility worklists directly from current Tracker data rather than hard-code these historical fixture values.

## S.4 Structured cause mentions among 53 completed reviews

Latest verified counts used in the final deep-dive specification:

- Hypertensive disorders: 13 = 24.5%
- Pregnancy-related sepsis: 12 = 22.6%
- Obstetric haemorrhage: 11 = 20.8%
- Malaria: 6 = 11.3%
- Indirect / pre-existing medical conditions: 6 = 11.3%
- Severe anaemia: 5 = 9.4%
- Abortion / ectopic / trophoblastic conditions: 5 = 9.4%
- Anaesthesia complications: 4 = 7.5%

Categories may overlap. Do not use a pie chart. Do not state that exactly 24.5% of maternal deaths were `caused by` hypertensive disorders unless a future clinically adjudicated mutually exclusive underlying-cause field supports that wording. Use `structured cause mentions`.

## S.5 Structured cause completeness

Among 53 completed reviews:

- 40 = 75.5% had at least one structured cause category selected
- 13 = 24.5% had no structured cause category selected

Do not label the 13 as `unknown causes`. Free-text or cause-chain information may still exist.

Facility-specific documentation examples from the later analysis included:

- Gulu Regional Referral Hospital: 6 of 11 completed maternal reviews had no structured cause category selected = 54.5%
- Kitgum General Hospital: 2 of 4 = 50.0%
- St. Mary's Hospital Lacor: 2 of 20 = 10.0%

Because denominators are small, always display counts and percentages together and avoid ranking facilities by maternal mortality quality based on these figures.

## S.6 Documented delay factors

Among 53 completed maternal reviews:

- documented delay before seeking appropriate care: 18 = 34.0%
- documented delay reaching a health facility: 12 = 22.6%
- both of these two domains: 7 = 13.2%
- at least one of the two available delay domains: 23 = 43.4%

The two domains overlap. Do not add their percentages. The analysed export did not provide a complete third-delay variable for delay in receiving appropriate care after arrival, so do not label this a complete `Three Delays` analysis.

Use non-blaming language: `A delay before seeking appropriate care was documented` rather than `women failed to seek care`.

## S.7 Facility stay before death

Among 51 completed reviews with usable stay-duration information:

- under 6 hours: 11
- 6 to <24 hours: 12
- total under 24 hours: 23 = 45.1%
- 24 to <48 hours: 5 = 9.8%
- 48 hours or more: 23 = 45.1%

This is an investigation signal. A short stay may reflect severe presentation, late arrival, referral case mix or other factors. It must not be interpreted as proof of poor facility care.

## S.8 Maternal confidentiality rules

District-level process performance may be shown because notification/review completion is programme performance. Clinical cause analysis should generally remain at Acholi/regional aggregate level unless a formally approved disclosure rule allows more granular analysis.

Do not expose to general dashboard users or third-party AI providers:

- names of deceased women
- personal identifiers
- event UIDs in presentation layers
- usernames/reviewer names
- exact death date + facility + rare cause combinations
- exact age + location + cause combinations
- detailed individual clinical narratives
- clinician names
- facility-by-rare-cause matrices that make a case identifiable
- accusations of negligence
- claims that a specific death was preventable unless formally adjudicated and authorised for presentation

The system may still perform authorised case-management/worklist functions for appropriately privileged MPDSR users, but that is a distinct security context from the aggregate performance dashboard and AI narrative layer.

# Appendix T. Verified ANC and Intrapartum Year-on-Year Regression Fixtures

## T.1 Acholi ANC regional comparison fixture

The verified regional comparison used 2024 Census population for FY2024/25 and 2025 projected population for FY2025/26.

| Indicator | FY2024/25 | FY2025/26 | Change |
|---|---:|---:|---:|
| ANC1 | 97.4% | 95.4% | -1.9 pp approximately |
| ANC first trimester | 38.7% | 41.4% | +2.7 pp |
| ANC4 | 59.3% | 58.3% | -1.1 pp approximately |
| ANC8 | 8.5% | 11.7% | +3.1 pp approximately |
| IPT3 | 64.3% | 63.2% | -1.1 pp |
| Hb testing | 33.0% | 35.9% | +2.9 pp |
| IFA | 84.3% | 181.3% | +97.1 pp; data-definition/reporting flag |
| Ultrasound | 27.9% | 35.5% | +7.5 pp approximately |
| Teenage pregnancy | 19.8% | 19.2% | -0.6 pp |

The region must be calculated from aggregate numerators and denominators, not the mean of nine LG percentages.

## T.2 Intrapartum regional comparison fixture

| Indicator | FY2024/25 | FY2025/26 | Interpretation |
|---|---:|---:|---|
| Institutional delivery | 71.4% | 67.6% | remained green but declined |
| C-section rate | 9.9% | 10.7% | within desired range both years |
| KMC | 78.2% | 69.0% | yellow -> red |
| Successful resuscitation | 101.9% | 121.8% | blue both years; not interpretable as performance |
| PMR /1,000 | 14.4 | 20.4 | yellow -> red; worsened |
| Fresh SB /1,000 | 5.7 | 5.9 | yellow both years |
| MMR /100,000 live births | 98.5 | 80.1 | green both years; improved regionally |

This fixture is useful for verifying inverse indicators, desired ranges, BLUE handling and year-specific population denominators.

## T.3 Selected district regression examples

Examples that should remain stable in tests when using the historical fixture data:

- Gulu District institutional delivery: 51.7% in FY2024/25 -> 48.8% in FY2025/26, yellow -> red.
- Gulu City C-section rate: 23.3% -> 24.9%, red -> red.
- Gulu City KMC: 119.2% BLUE in FY2024/25 -> 48.1% red in FY2025/26.
- Kitgum PMR: 17.6 -> 24.2 per 1,000, yellow -> red.
- Pader fresh stillbirth rate: 5.2 -> 3.9 per 1,000, yellow -> green.
- Kitgum MMR: 185.0 -> 66.2 per 100,000 live births, yellow -> green.

# Appendix U. Dashboard Visual and Interaction Contract - Latest Aesthetic Decisions

## U.1 Preserve the original dashboard format

The user explicitly prefers the original blue/DHIS2-like dashboard format. Later mock-ups that introduced large green scenic backgrounds, a major `Uganda at a Glance` hero section or unrelated programme modules drifted too far from the preferred design and should not be used as the baseline.

The reference visual language is:

- dark navy/blue left sidebar
- Ministry of Health branding area
- light blue/white main canvas
- clean white analytical cards
- navy titles and labels
- subtle borders and shadows
- RAG cells that resemble health-sector scorecards
- compact top scope/period/compare controls
- information-dense but orderly tables
- charts and maps integrated into cards
- AI insights presented as a supporting analytical panel, not a dominant chat interface
- downloads visibly available

## U.2 Natural background requirement

The user wants the experience to feel warmer and more natural, but the treatment must be **subtle**. Do not redesign the screen around scenery or decorative green themes.

Preferred treatment:

- preserve the blue/DHIS2 character
- use a very light cool-blue/off-white page background rather than stark pure white
- optionally use extremely faint organic curves, soft gradient waves or botanical silhouettes at the extreme edges/background only
- preserve strong white card surfaces and data contrast
- avoid loud green sidebars or nature photography
- do not let decoration compete with analytics
- natural detail should be noticeable mainly as polish, not as content

The guiding phrase is: **the analytics remain the hero; the natural background is atmospheric only.**

## U.3 Current left navigation for MNCH release

Preferred primary items:

- Overview
- MNCH
- Immunization
- MPDSR
- Maps
- Trends
- Reports
- Exports
- AI Insights
- Admin, permission-gated

ANC, intrapartum and newborn may be nested under MNCH or represented as workspace tabs. Avoid adding full HIV/TB/general-malaria navigation to the first MNCH visual release.

## U.4 National overview screen

The national overview should contain:

- title: Health Performance Intelligence / National overview
- scope: Uganda
- user role indicator
- period selector
- comparison period selector
- geography selector/search
- headline KPI cards using verified national values when available
- regional performance map
- national/regional scorecard
- AI performance insights / priority insights
- monthly or multi-year trends
- downloads

When national population and production DHIS2 data are not yet loaded, mock-up figures must be labelled internally as illustrative and must never leak into production regression fixtures.

## U.5 Regional/sub-regional screen

Example reference: Acholi sub-region.

Required:

- district map
- district performance scorecard
- selected indicator control
- priority insights
- district ranking/priority table
- trend chart
- scope/period/compare controls
- drill-down to district

## U.6 District facility-performance screen

Required because the user explicitly asked for an image/screen showing comparison of different facilities inside a selected district.

Main table columns should be configurable and include facility, level and selected programme indicators. Insights should name facilities driving strong performance, gaps, data-quality issues or unusual trends. A top/bottom facility view is useful, but do not rank on unstable mortality ratios without context.

## U.7 Facility profile

The facility profile should show:

- facility name, district, sub-county, ownership, level
- reporting period
- catchment population and source/status
- authorised Edit Population action where needed
- KPI cards
- monthly service trends
- indicator scorecard
- data-quality alerts
- AI summary
- recommended actions
- Excel, PowerPoint and report downloads

If a required facility population is missing, show an inline call-to-action to enter it rather than silently suppressing the indicator.

## U.8 MPDSR workspace

The MPDSR view must systematically cover **both perinatal and maternal deaths**. Do not allow the deep-dive screen to become maternal-dominated.

At minimum:

1. Combined notification/review scorecard with reported, notified, % notified, % notified on time, reviewed, % reviewed and % reviewed on time for both perinatal and maternal deaths.
2. Perinatal process trend view.
3. Perinatal cause/documentation deep dive.
4. Maternal cause/delay/documentation deep dive.
5. Active event worklist or count for authorised users.
6. Data-quality/reconciliation findings.
7. No arbitrary RAG bands beyond the agreed perinatal and maternal process targets.

# Appendix V. Chart Grammar and Insight Generation Rules

## V.1 Chart-selection rules

The system should select charts because they answer an analytical question, not merely because they look attractive.

| Analytical question | Preferred visual |
|---|---|
| Performance across org units | RAG scorecard / heatmap table |
| Trend over time | Line chart |
| Reported perinatal composition | Stacked or 100% stacked columns |
| Burden share versus service volume | Scatter/dot plot with equality line |
| Cause mentions with overlapping categories | Horizontal bar chart |
| Persistence of events across months | Heatmap |
| Desired target range | Chart with shaded target band, e.g. C-section |
| Top contributors to a gap | Ranked bars / Pareto |
| Year-on-year scorecard | Side-by-side period columns |
| Continuum/retention | Connected bars or step/funnel-like view only if denominators support it |
| Geographic variation | Choropleth map |

Do not use pie charts when categories can overlap. Do not use 3D charts. Do not use decorative charts that hide denominators or units.

## V.2 Insight engine primitives

The deterministic analytics engine should compute reusable facts before AI is called:

- current value
- previous value
- absolute change
- percentage-point change
- relative change where meaningful
- target gap
- status current/previous
- status transition
- rank
- percentile
- count of child org units by status
- largest improvement/deterioration
- largest contribution to numerator or burden
- contribution to overall gap
- Pareto set explaining 80% of gap
- trend slope
- consecutive improvement/deterioration periods
- anomaly flag
- zero/missing/duplicate pattern
- numerator/denominator relationship
- data-quality flags
- freshness timestamp

AI should narrate these verified facts rather than derive them from raw values independently.

## V.3 Direction-aware narrative

The narrative engine must know whether a metric is higher-is-better, lower-is-better, desired-range or data-quality-only.

Examples:

- PMR rising is deterioration, not improvement.
- Teenage pregnancy falling is improvement.
- C-section rising from 4% to 8% may be improvement because it moves into the desired range; rising from 18% to 24% is deterioration.
- A resuscitation value moving from 101.9% to 121.8% is not improvement; both are BLUE and not interpretable.

## V.4 Simple-English requirement

For slide/report insights, use simple health-programme English. Avoid over-academic wording. Prefer direct statements with counts, percentages and units. Avoid generic phrases such as `there is variation across districts` when the engine can say which districts and by how much.

# Appendix W. DHIS2 API Contract - Verified Technical Notes

The DHIS2 integration required for this product is feasible with current official APIs. The platform should use a combination of aggregate Analytics, Event Analytics and Tracker Events rather than depend on one endpoint for every purpose.

Official references verified against current DHIS2 documentation in September 2026:

- Analytics API: https://docs.dhis2.org/en/develop/using-the-api/dhis-core-version-242/analytics.html
- Tracker API: https://docs.dhis2.org/en/develop/using-the-api/dhis-core-version-master/tracker.html
- Analytics scheduling / continuous analytics tables: https://docs.dhis2.org/en/use/user-guides/dhis-core-version-242/maintaining-the-system/scheduling.html

## W.1 Aggregate analytics

`/api/analytics`

Use for routine aggregated programme values such as ANC, immunization, delivery and other aggregate indicators. Queries can specify data/indicator dimensions, periods and organisation units. The authenticated user must have permission to export/analyse the requested organisation units.

## W.2 Event Analytics

The Event Analytics API supports querying individual events as analytical rows and aggregating event data. Use it for efficient event-level analytical extracts and cause/status aggregations.

The platform should be able to select program, program stage, start/end date, org units and requested data elements/attributes. Each query row can represent an event with event identifier, program-stage/date/org-unit metadata and requested dimensions.

## W.3 Tracker Events

Current Tracker API endpoint:

`GET /api/tracker/events`

and single-event retrieval:

`GET /api/tracker/events/{uid}`

Current Tracker event objects can include event status, program, program stage, org unit, `occurredAt`, created/updated timestamps and event `dataValues`. This makes Tracker suitable for current operational state, ACTIVE/COMPLETED worklists and detailed event validation.

Do not build against deprecated pre-v42 `/api/events` endpoints. DHIS2 v42 removed deprecated tracker endpoints; use `/api/tracker/...`.

## W.4 Hybrid MPDSR strategy

Recommended split:

- Event Analytics: analytical cohort extraction, aggregates, grouping, efficient dashboards.
- Tracker Events: current event object/state, recent updates, active-event worklists, detailed data-value validation.

This avoids stale operational views when analytics tables have not refreshed while retaining efficient analytical queries for large cohorts.

## W.5 Analytics-table freshness

DHIS2 analytics queries rely on analytics tables. New or changed data become visible to analytics after the relevant table update. DHIS2 supports scheduled analytics-table jobs and continuous analytics updates, where recent changes can be updated frequently while full updates occur daily.

The platform should expose `data_as_of` / `analytics_refreshed_at` and should use Tracker current-state retrieval when the user needs immediate operational information such as active maternal/perinatal review events.

## W.6 Metadata and version compatibility

Do not hard-code production UIDs in source code. Maintain a versioned metadata mapping registry. The connector should discover/validate:

- program UID
- program-stage UID
- data-element UID
- category option combinations where relevant
- organisation-unit UID
- indicator/data-set metadata
- last metadata sync

A connection health check should verify DHIS2 version and required endpoint behaviour before enabling a programme module.

# Appendix X. AI Gateway, Cheap API Strategy and Sensitive Data Controls

## X.1 AI is embedded but not required for mathematics

The user is comfortable using inexpensive AI APIs such as DeepSeek or other providers. The architecture should therefore include AI from the start, but calculations and file layout must remain deterministic.

AI is valuable for:

- natural-language interpretation of verified results
- `Why is this red?`
- `Ask the Data`
- key findings
- management summaries
- action recommendations grounded in configured guidance
- narrative report generation
- PowerPoint narrative text
- cross-indicator synthesis

AI is not responsible for:

- formulas
- denominators
- RAG colours
- parent aggregation
- exact export tables
- access control
- map boundaries
- data-quality calculations

## X.2 Provider-agnostic gateway

Recommended logical contract:

`Application -> AI Gateway -> configured provider/model`

Provider configuration should include:

- provider name
- base URL
- model
- encrypted API key reference
- cost class
- max tokens
- timeout
- allowed data sensitivity class
- fallback provider/model
- enabled/disabled status

This permits cheap models for routine summaries and stronger models for complex synthesis without coupling the application to one vendor.

## X.3 Cost control

Implement:

- evidence-package caching by calculation run
- narrative caching by evidence hash + prompt version + model
- per-user/per-role quotas if needed
- maximum prompt/evidence size
- cheap model default for routine insights
- deterministic fallback when AI is unavailable
- async generation for long reports
- token/cost logging by provider and feature

## X.4 Evidence-safe prompts

The AI request should contain a structured evidence package, for example:

```yaml
scope: Pader District
period: FY2025/26
indicator: ANC4 Coverage
value: 49.7
unit: percent
target: 75
status: red
previous_value: 53.4
change_pp: -3.7
numerator: <verified count>
denominator: <verified expected pregnancies>
data_quality_flags: []
top_contributors: [...]
method_version: anc4_v1
```

The model is instructed to explain and synthesise only these facts. If evidence is insufficient for causation, it must say that the pattern requires review rather than inventing a reason.

## X.5 Sensitive MPDSR AI handling

Do not routinely send raw maternal/perinatal line-list records or free-text narratives to third-party AI providers. The backend should first aggregate and minimise the data. The AI should receive safe facts such as counts, percentages, broad cause categories, timing gaps and documented delay proportions.

If a future deployment uses a locally controlled model and governance permits deeper analysis, that can be a separate sensitivity tier. The default external-API tier should remain aggregate/minimised.

## X.6 Prompt-injection and untrusted free text

Clinical narrative fields and uploaded notes are untrusted data. They must never be concatenated into system instructions. If free text is analysed, use strict delimitation, sanitisation, allowlisted tasks and output schemas. Prefer deterministic thematic coding or a controlled offline workflow for sensitive clinical narratives.

# Appendix Y. Publishing and Reproducible Output Contract

## Y.1 Excel

Excel should be generated by code, not by an LLM. Recommended workbook sheets:

1. Scorecard
2. Indicator Calculations
3. Raw/Source Data or Extract Summary depending on permissions
4. Population / Denominators
5. Methodology / Indicator Dictionary
6. Data Quality
7. Metadata / Run Information

The scorecard should preserve the same RAG/BLUE logic as the dashboard. Count cells remain neutral. Formula fields and denominator provenance should be visible in calculation/methodology sheets. Sensitive event rows should only be included when the user's export permission permits them.

## Y.2 PowerPoint

PowerPoint generation should be deterministic and template-driven. The system should maintain approved slide templates such as:

- MNCH scorecard
- ANC year-on-year comparison
- intrapartum year-on-year comparison
- trend + composition deep dive
- map + scorecard
- district facility performance
- MPDSR combined scorecard
- perinatal process deep dive
- perinatal causes/documentation
- maternal MPDSR deep dive
- priority actions / conclusion

The calculation engine supplies tables/charts; AI supplies bounded narrative text if enabled; the template engine controls placement, sizing, fonts, colours and footers.

The final PPTX must be editable. Do not flatten everything into images.

## Y.3 Narrative report

Reports can be produced as Word/PDF using a deterministic section template plus AI-generated narrative from verified evidence. The report must include scope, period, data source, formula/method version, findings, data-quality limitations and recommendations. It should not present AI speculation as fact.

## Y.4 Current-view export

An export should capture the exact analytical context:

- user-authorised scope
- selected geography
- selected programme/module
- period
- comparison period
- filters
- indicator definition versions
- population version
- source data/as-of timestamp
- calculation run ID

This allows the same view to be reproduced later.

# Appendix Z. IDE Prompt Factory and Phased Build Contract

The handoff is designed so the IDE can generate its own implementation prompts. The expected approach is not one giant coding instruction and not random iterative prompting. Use a phased prompt factory.

## Z.1 Overall build plan

Preferred serious MNCH release:

- 7 phases
- 26 detailed implementation prompts
- approximately 1,300-1,500 words per prompt where that depth is useful

The 26 prompts already specified in the main blueprint remain the planned sequence. The IDE may split a prompt only if the task proves too large for safe implementation; it must not merge unrelated phases merely to reduce prompt count.

## Z.2 Prompt generation template

Every generated coding prompt should contain these sections:

1. **Context to re-read** - identify the relevant sections of this handoff and current repository state.
2. **Objective** - one bounded implementation goal.
3. **Why this matters** - relationship to the architecture and downstream dependencies.
4. **Existing contracts that must not change** - formulas, permissions, API shapes, UI tokens, database decisions already implemented.
5. **Required deliverables** - exact code, migrations, tests, docs or screens expected.
6. **Data contracts / schemas** - required input/output structures.
7. **Edge cases** - missing populations, no data, >100%, inverse indicators, permission denial, stale analytics, etc.
8. **Security/privacy requirements** - especially for MPDSR and secrets.
9. **Testing requirements** - unit, integration, regression and UI tests.
10. **Acceptance criteria** - observable pass/fail conditions.
11. **Do not do** - explicit anti-goals and forbidden shortcuts.
12. **State handoff** - what implementation-state file, changelog or decision record must be updated after completion.

## Z.3 Prompt factory meta-instruction for the IDE

The IDE may use the following as its own internal prompt-generation rule:

> Read the Ultimate IDE Handoff and the current repository state before generating the next implementation prompt. Preserve all existing architectural contracts and latest explicit user decisions. Generate one implementation prompt focused on the next unfinished item in the approved phase plan. The prompt should be specific enough for another coding agent to implement without inventing formulas, UIDs, targets or permissions. Include deliverables, data contracts, edge cases, tests, acceptance evidence and anti-goals. Where required information is not yet supplied, create a configuration placeholder or blocked task and name exactly what is missing. Never silently fill a programme-definition gap from general knowledge. At completion, require the coding agent to update implementation-state documentation and provide test evidence.

## Z.4 Phase gates

### Gate after Phase 1 - architecture/foundations

Do not proceed unless:

- repo structure is stable
- environment/secrets model is defined
- database migrations work
- RBAC/geography scope model exists
- audit strategy exists
- CI test command exists

### Gate after Phase 2 - data/calculation foundation

Do not proceed unless:

- DHIS2 aggregate connector can query a controlled fixture/mock
- Tracker/Event connector can retrieve event-shaped fixture data
- geography/population resolver passes tests
- indicator engine reproduces gold-standard formulas
- RAG/BLUE engine passes edge cases
- data-quality engine can store/return flags

### Gate after Phase 3 - MNCH domain modules

Do not proceed unless:

- ANC, intrapartum/newborn, immunization and MPDSR modules use the same generic engines
- no module contains hidden hard-coded denominator logic that belongs in configuration
- regression fixtures pass

### Gate after Phase 4 - UI

Do not proceed unless:

- national, regional, district-facility and facility drill-down are permission-safe
- UI matches the approved blue/DHIS2-like visual contract
- the district facility-performance screen exists
- maps, tables and charts handle no-data and BLUE states correctly

### Gate after Phase 5 - AI

Do not proceed unless:

- AI sees verified evidence rather than raw unvalidated calculations
- sensitive MPDSR data are minimised
- provider failure leaves deterministic dashboard functionality intact
- outputs can be traced to evidence and model/prompt version

### Gate after Phase 6 - publishing

Do not proceed unless:

- Excel/PPTX/report outputs reproduce dashboard calculations exactly
- current-view context is embedded in output metadata/footers
- PPTX objects remain editable

### Gate after Phase 7 - production

Production readiness requires security review, performance testing, backup/restore evidence, observability, deployment documentation, admin documentation, population and metadata loading, and sign-off on all unresolved programme configuration.

# Appendix AA. Recommended Repository Documentation and State Files

The IDE should create and continuously maintain human-readable project documentation inside the repository. Suggested files:

- `docs/ULTIMATE_HANDOFF.md` - copy of this file or a linked canonical version
- `docs/IMPLEMENTATION_STATE.md` - completed prompts, current phase, blockers, next task
- `docs/DECISIONS.md` - architectural decision log
- `docs/INDICATOR_DICTIONARY.md` - current seeded indicator definitions and versions
- `docs/POPULATION_RULES.md`
- `docs/DHIS2_MAPPING_STATUS.md`
- `docs/SCREEN_CONTRACTS.md`
- `docs/AI_GOVERNANCE.md`
- `docs/EXPORT_CONTRACTS.md`
- `docs/SECURITY_MODEL.md`
- `docs/DEPLOYMENT.md`
- `tests/fixtures/acholi_gold_standard.*` - machine-readable regression fixtures derived from the validated examples in this handoff

Each implementation prompt should update `IMPLEMENTATION_STATE.md` and, when a decision changes, `DECISIONS.md`.

# Appendix AB. Data Quality Engine - Detailed Rule Families

The data-quality engine should not be a list of one-off if-statements inside dashboard code. It should be a rule registry capable of applying rules by programme, indicator, dataset or event type.

## AB.1 Rule categories

### Completeness

- expected reporting unit has no value for required period
- event missing required field
- review missing cause field
- facility population required but absent

### Logical consistency

- numerator greater than a bounded denominator
- child category sum greater than known total
- review date earlier than death date
- notification date earlier than death date
- maternal death line-list count inconsistent with reported count

### Plausibility

- bounded percentage >100%
- unexpected negative value
- impossible age/date combination if such data are in scope and approved
- abrupt order-of-magnitude change

### Reconciliation

- line-list count > aggregate reported count
- aggregate parent not equal to sum of child raw counts where exact reconciliation is expected
- notification and review stage counts cannot be reconciled by shared ID where linkage exists

### Timeliness

- dataset/report submitted late
- notification outside allowed window
- review outside allowed window
- active event older than expected completion window

### Metadata/data-source quality

- mapped UID removed or renamed
- data element value type changed
- analytics freshness too old
- population version missing for selected year
- org-unit mapping ambiguous

## AB.2 Severity and status

Suggested status model:

- `INFO` - notable but not necessarily wrong
- `WARNING` - needs review but analysis may continue
- `ERROR` - indicator should be BLUE/non-interpretable
- `BLOCKING` - calculation/export cannot safely proceed

Data-quality severity must be configurable by rule.

## AB.3 Resolution workflow

A DQ issue should contain:

- rule ID/version
- scope/org unit
- programme/indicator/event class
- period
- observed values
- expected relationship
- first detected
- last detected
- status: open, acknowledged, resolved, suppressed with reason
- assigned user/team if action tracking is enabled
- resolution note
- resolved by/date

Resolving a DQ issue in this platform does not rewrite DHIS2 automatically unless a future approved write-back workflow is implemented. Default behaviour is read-only analytics plus documented follow-up.

# Appendix AC. Statistical Trend, Dip, Anomaly and Contribution Engine

## AC.1 Trend engine

For each indicator and geography, the engine should support monthly, quarterly, annual and financial-year views where source frequency permits. It should calculate direction, absolute change, percentage-point change, moving summaries and persistence.

## AC.2 Dip detection

Prior operational analyses included a requirement to identify facility/indicator/month `dips` relative to a normal-period mean. The generic analytics engine should support a configurable dip detector such as:

- define a baseline window
- calculate expected/mean or robust median for that org unit/indicator
- calculate absolute and relative departure
- require minimum denominator/data completeness
- rank largest negative departures
- suppress known campaign or reporting artefacts where configured

The exact statistical method should be configurable and tested before being labelled an anomaly. A simple transparent robust rule is preferable to an opaque ML model in the first release.

## AC.3 Contribution analysis

For a parent indicator gap or burden, calculate each child org unit's contribution using raw components. Example questions:

- Which districts contribute most to regional perinatal deaths?
- Which facilities account for most of a district's missed ANC4 target?
- Which districts explain most of the notification shortfall?

Contribution should use the relevant numerator/gap arithmetic, not simply rank percentages.

## AC.4 Pareto analysis

Rank child contributions and return the smallest set explaining a configurable cumulative share, commonly 80%. The UI can say, for example, `Gulu City and Kitgum account for about 90% of the net notification gap` when supported by the fixture.

## AC.5 Anomaly detection

Initial release should prioritise explainable statistical rules:

- rolling median/MAD
- IQR-based outlier
- change threshold
- consecutive deterioration
- unusual zero after sustained non-zero reporting
- abrupt denominator change

More advanced forecasting/anomaly models can be added later. The output must include the reason for the flag and the baseline used.

# Appendix AD. Map and GeoJSON Contract

## AD.1 Mapping levels

Support maps for national, region/sub-region, district and sub-county polygons where boundaries are available, plus facility points.

## AD.2 GeoJSON ingestion

An authorised administrator should be able to upload GeoJSON and map its feature identifier property to internal org units. The system should validate geometry, CRS, duplicate identifiers and unmatched org units before activation.

## AD.3 Map state

Map colour should derive from the selected indicator status/threshold. Distinguish:

- normal performance colours: green/yellow/red
- BLUE data-quality state where appropriate
- no data: neutral grey rather than implying quality or performance

## AD.4 Map click behaviour

Clicking a geography should open a contextual drawer or drill-down containing:

- org unit name
- current value and unit
- status
- numerator/denominator
- target
- previous period and change
- sparkline
- data-quality flags
- `Open detailed view`

Permission checks occur on the API call for the new scope.

# Appendix AE. Indicator Lineage and Evidence Drawer

Every computed indicator should have a lineage drawer accessible from the scorecard or KPI card. Minimum content:

- indicator name
- indicator code/version
- programme/module
- selected geography
- selected period
- numerator definition and observed numerator
- denominator definition and observed denominator
- population source/year/version if applicable
- formula
- multiplier/unit
- target and threshold version
- current RAG/BLUE status
- source system and DHIS2 UIDs
- extraction/analytics freshness timestamp
- calculation run ID
- child contribution summary
- data-quality flags
- comparison value and definition version

The drawer is essential for trust. A stakeholder who asks `Where did 58.3% come from?` should receive a complete answer without exporting raw data manually.

# Appendix AF. No-Data, Zero, N/A and BLUE Semantics

The system must not collapse distinct states into `0`.

- **0**: valid numeric zero with known denominator/context.
- **No data**: expected data missing.
- **N/A**: indicator not applicable, for example no birth-asphyxia cases for a resuscitation denominator.
- **Not assessable**: required timing/date field malformed or missing.
- **BLUE**: value exists but is not safely interpretable as normal performance because of a logical/reconciliation issue.

Exports, maps, tables and AI evidence must preserve these states explicitly.

# Appendix AG. Small-Number and Mortality Interpretation Rules

Maternal deaths and some facility-level rare outcomes have small denominators. The platform should:

- show underlying counts with MMR and district process percentages where feasible
- avoid automatic `best/worst` narratives based on one versus two deaths
- allow confidence intervals as a future option but do not introduce them silently into existing scorecards
- avoid causal attribution
- distinguish burden concentration from individual risk
- surface referral/case-mix context when supported by data

For Gulu City in the historical fixture, referral information in completed reviews indicated a substantial referral component. This supports cautious wording that burden concentration should be interpreted alongside referral/case mix, but it does not explain away the observed outcomes.

# Appendix AH. AI Narrative Style and Clinical Interpretation Guardrails

AI-generated insights should be short, specific and evidence-linked. Examples of preferred structure:

1. State the verified result.
2. Compare with target/previous period.
3. Name the geography or component driving the result if supported.
4. State a cautious programme implication.
5. State a DQ caveat where relevant.

Avoid:

- unsupported causal claims
- generic `performance varied` language
- judging a facility based solely on an implausible value
- treating BLUE as improvement
- blaming patients for documented delays
- implying a referral centre's raw burden is directly comparable to a lower-level facility without context
- fabricated recommendations not linked to configured programme guidance

The preferred language in regional presentations is simple English.

# Appendix AI. Suggested Technical Stack - Flexible but Coherent

The detailed blueprint proposes a modern web stack. The implementation should remain pragmatic and can reuse Python expertise.

Recommended baseline:

- Frontend: React / Next.js or equivalent modern component framework
- Styling/design system: utility CSS plus reusable component library
- Charts: Apache ECharts or Plotly
- Maps: MapLibre or Leaflet
- Backend: Python, with FastAPI or Flask depending repository strategy
- Database: PostgreSQL + PostGIS
- Queue/background jobs: Celery/RQ or equivalent
- Cache: Redis where useful
- Excel: openpyxl or an equivalent deterministic workbook library
- PowerPoint: PptxGenJS or python-pptx with template discipline
- Report generation: deterministic DOCX/PDF template pipeline
- AI: provider-agnostic HTTP gateway supporting DeepSeek/OpenAI/Anthropic/other configured providers
- Deployment: containerised environments with dev/staging/prod separation

The stack is less important than preserving contracts: generic indicator engine, secure permissions, reproducible calculations, event/aggregate separation and deterministic publishing.

# Appendix AJ. API and Service Boundary Suggestions

Suggested backend service boundaries:

- Auth/RBAC service
- Organisation/geography service
- Population service
- DHIS2 metadata service
- DHIS2 aggregate ingestion service
- Tracker/Event ingestion service
- Indicator calculation service
- Threshold/status service
- Data-quality service
- Trend/analytics service
- Map data service
- Evidence package service
- AI gateway service
- Export service
- Admin/config service
- Audit service

A monolithic Python application can still implement these as modules initially. The boundary is logical; microservices are not required for the first release.

# Appendix AK. Non-Negotiable UI Behaviours from the User

1. Do not drift away from the approved screen format when polishing backgrounds.
2. The natural background must be subtle.
3. Prefer blue/DHIS2-like visual identity over a loud green theme.
4. Preserve the exact analytical card/scorecard feel of the original mock-ups.
5. The district facility-comparison screen is a first-class view.
6. National is the landing page only for users with national scope; lower-scope users land at their own highest authorised level.
7. Facility population entry is prompted only when needed and not already stored.
8. Dashboard should be beautiful, but beauty must not reduce analytical density or readability.
9. Excel/PPTX/report downloads should look polished and should match the approved analysis style.
10. AI should feel embedded and useful, not like a separate gimmick.

# Appendix AL. Future Programme Expansion Roadmap

The generic architecture should later support:

- full Malaria programme surveillance, including routine case indicators and potentially climate-linked intelligence
- HIV programme indicators
- TB programme indicators
- Nutrition
- WASH
- HMIS reporting completeness/timeliness
- other programme scorecards configured through the indicator registry

Existing historical work on malaria surge prediction and climate integration demonstrates a future pathway for adding CHIRPS rainfall, ERA5-Land temperature/dewpoint and forecasting to a malaria intelligence module, but that is not part of the first MNCH build and should not delay the core platform.

# Appendix AM. Bootstrap Instruction to Give the IDE Before It Generates Any Coding Prompt

The following text can be used as the first instruction to an IDE/agent after this Markdown file is uploaded:

> Treat `ULTIMATE_IDE_HANDOFF_Uganda_Health_Performance_Intelligence_Platform.md` as the canonical product and engineering context for this project. Read it before proposing architecture or code. Do not start by redesigning the product. First produce a context inventory containing: product purpose, scope-aware landing rule, geography hierarchy, permission dimensions, data-source strategy, indicator engine principles, all currently agreed MNCH denominator families, BLUE/RAG logic, event/MPDSR strategy, AI boundaries, publishing requirements, visual design contract, unresolved dependencies and the seven-phase/twenty-six-prompt plan. Then identify any conflicts or missing production inputs without filling them from general knowledge. After that, create the implementation prompt plan. Each coding prompt must preserve earlier contracts, include tests and acceptance criteria, and update implementation state. Calculations and colour classifications are deterministic; AI only interprets verified evidence. Never invent DHIS2 UIDs, national populations, facility populations, programme targets or clinical causes. UI mock-up numbers are illustrative unless explicitly listed as regression fixtures in the handoff.

# Appendix AN. Production Inputs Still Required Before National Rollout

This handoff is intentionally complete about architecture and currently agreed formulas, but several production inputs must still be supplied or confirmed. The IDE should represent these as explicit configuration dependencies:

1. Full Uganda population master by configured geography and year, including sub-counties and projections.
2. Approved facility catchment populations where available.
3. National analytical region/sub-region grouping and mapping to DHIS2 org units.
4. Production DHIS2 base URL and authentication method.
5. Production program, program-stage and data-element UIDs for all MNCH/EPI/MPDSR indicators.
6. Final performance thresholds for EPI indicators where they have not yet been explicitly agreed in the source material.
7. Approved national/district/sub-county GeoJSON boundaries and facility coordinates where not already available through DHIS2.
8. Final organisation branding assets and exact colour tokens if Ministry-approved branding requires them.
9. Final AI provider(s), model(s), data-processing agreement/governance and cost limits.
10. Final PowerPoint/Excel/report master templates after visual sign-off.
11. Production deployment environment, DNS, secret management, backup policy and monitoring endpoints.
12. Data-retention and audit policy for event-level MPDSR data.

Missing production inputs must not block development of the generic engine when they can be represented through fixtures/configuration, but they must block false claims of production readiness.



# Appendix AO. Source Methodology Snapshots Included for IDE Cross-Checking

The following source snapshots are included as reference material. Where an older source wording differs from a later explicit decision in the Ultimate Handoff, the later decision takes precedence. These snapshots are useful because they preserve the original context and terminology used when the formulas were agreed.

## AO.1 ANC methodology snapshot

**Methodology and Instructions for PowerPoint Presentation Development**

*FY 2025/26 (July 2025 - June 2026)*

Acholi Sub-region, Uganda

# 1. Purpose of the Analysis

The purpose of this analysis is to assess maternal health and antenatal care performance across districts and Gulu City in the Acholi Sub-region using routine ANC service data for FY 2025/26 (July 2025-June 2026).

The analysis will compare districts/city across a set of key ANC indicators, calculate percentage performance using agreed denominators, classify performance using a traffic-light scorecard, and identify:

- High-performing districts

- Moderate-performing districts

- Poor-performing districts

- Major gaps in maternal health service utilisation

- Areas requiring programmatic attention

- Overall Acholi Sub-region performance

The analysis should cover:

- Agago

- Amuru

- Gulu City

- Gulu District

- Kitgum

- Lamwo

- Nwoya

- Omoro

- Pader

- Acholi Sub-region aggregate

# 2. Data Sources

## Dataset 1: ANC Service Data

The ANC dataset covers July 2025 to June 2026, corresponding to FY 2025/26. It contains the following raw indicators:

1\. ANC first visit - ANC1

2\. ANC first visit occurring during the first trimester

3\. ANC fourth visit - ANC4

4\. ANC eighth contact/visit - ANC8

5\. Pregnant women receiving IPT3

6\. Pregnant women tested for anaemia using Hb testing at ANC1

7\. Pregnant women receiving at least 30 iron and folic acid tablets

8\. Pregnant women receiving an obstetric ultrasound scan during ANC

9\. ANC1 among girls aged 15-19 years

10\. ANC1 among girls aged below 15 years

## Dataset 2: Population

The population dataset contains the 2024 Census population and population projections from 2025 onwards.

**For this analysis, use the 2025 projected population.**

Do not use the 2024 Census population or the 2026 projection for the calculations.

The justification is that the ANC reporting period is FY 2025/26, which begins in 2025, and therefore the agreed population denominator is the 2025 projected population.

# 3. General Population-Based Denominator

For ANC coverage indicators representing the expected number of pregnancies, use:

**Expected Pregnancies = 5% x Population (2025)**

**Expected Pregnancies = Population (2025) x 0.05**

This expected pregnancy population will serve as the denominator for:

- ANC1 coverage

- ANC4 coverage

- ANC8 coverage

- IPT3 coverage

It should be calculated separately for every district/city.

# 4. ANC First Visit Coverage

This measures the proportion of expected pregnant women who attended ANC at least once.

## Numerator

Total number of women attending ANC1 during FY 2025/26.

## Denominator

5% of the district/city 2025 population.

## Formula

**ANC1 Coverage = ANC1 / (0.05 x Population 2025) x 100**

## Target

**95%**

## Scorecard classification

| **ANC First Visit** | **Classification** |
|---------------------|--------------------|
| \>=95%              | Green              |
| 75.0%-94.9%         | Yellow             |
| \<75%               | Red                |

Coverage values exceeding 100% should not automatically be capped at 100%. They should remain visible because they may reflect utilisation by populations outside the estimated catchment, population-estimation differences, reporting patterns, or other service utilisation dynamics.

# 5. First Trimester ANC Attendance

This is a timing/early-booking indicator rather than a population-based coverage indicator. It assesses the proportion of ANC1 clients who began ANC during the first trimester of pregnancy.

## Numerator

Number of women whose ANC first visit occurred during the first trimester.

## Denominator

Total ANC1 attendance.

## Formula

**First Trimester ANC = ANC1 First Trimester / ANC1 x 100**

## Target

**45%**

## Scorecard classification

| **First Trimester ANC Attendance** | **Classification** |
|------------------------------------|--------------------|
| \>=45%                             | Green              |
| 30.0%-44.9%                        | Yellow             |
| \<30%                              | Red                |

This indicator should be interpreted as an indicator of early ANC initiation. A district can therefore have good ANC1 coverage but still perform poorly in early booking if many women begin ANC late.

# 6. ANC Fourth Visit Coverage

This measures continued utilisation of antenatal care through at least four ANC visits.

## Numerator

Number of women reaching ANC4.

## Denominator

5% of the 2025 population.

## Formula

**ANC4 Coverage = ANC4 / (0.05 x Population 2025) x 100**

## Target

**75%**

## Scorecard classification

| **ANC Fourth Visit** | **Classification** |
|----------------------|--------------------|
| \>=75%               | Green              |
| 50.0%-74.9%          | Yellow             |
| \<50%                | Red                |

The relationship between ANC1 and ANC4 should also be discussed because a large decline between first attendance and fourth attendance suggests poor continuity or retention in ANC.

# 7. ANC Eighth Contact Coverage

This measures the proportion of expected pregnant women who complete/reach the eighth ANC contact.

## Numerator

Number of women reaching the 8th ANC contact.

## Denominator

5% of the 2025 population.

## Formula

**ANC8 Coverage = ANC8 / (0.05 x Population 2025) x 100**

## Target

**15%**

## Scorecard classification

| **ANC Eighth Contact** | **Classification** |
|------------------------|--------------------|
| \>=15%                 | Green              |
| 7.0%-14.9%             | Yellow             |
| \<7%                   | Red                |

ANC8 should be interpreted carefully because utilisation of the eight-contact model may still be substantially lower than ANC1 or ANC4. The analysis should particularly highlight districts where women enter ANC but very few progress to the eighth contact.

# 8. IPT3 Coverage

This measures uptake of at least the third dose of intermittent preventive treatment for malaria during pregnancy.

## Numerator

Number of pregnant women receiving IPT3.

## Denominator

5% of the 2025 population.

## Formula

**IPT3 Coverage = IPT3 / (0.05 x Population 2025) x 100**

## Target

**75%**

## Scorecard classification

| **IPT3**    | **Classification** |
|-------------|--------------------|
| \>=75%      | Green              |
| 50.0%-74.9% | Yellow             |
| \<50%       | Red                |

IPT3 should be considered both a maternal health and malaria-in-pregnancy prevention indicator.

# 9. Haemoglobin Testing at ANC1

This is primarily a quality-of-care indicator. It assesses whether women attending ANC1 receive haemoglobin testing for anaemia.

## Numerator

Number of pregnant women tested for haemoglobin/anaemia during ANC1.

## Denominator

Total ANC1 attendance.

## Formula

**Hb Testing = Pregnant women tested for Hb / ANC1 x 100**

## Target

**75%**

## Scorecard classification

| **Haemoglobin Testing at ANC1** | **Classification** |
|---------------------------------|--------------------|
| \>=75%                          | Green              |
| 50.0%-74.9%                     | Yellow             |
| \<50%                           | Red                |

This indicator should not use population as its denominator because the question is: Of the women who actually attended ANC1, how many received Hb testing?

# 10. Iron and Folic Acid Supplementation

This assesses supplementation among women attending ANC.

## Numerator

Number of pregnant women receiving at least 30 iron and folic acid tablets.

## Denominator

Total ANC1 attendance.

## Formula

**IFA Coverage = Pregnant women receiving at least 30 IFA tablets / ANC1 x 100**

## Target

**95%**

## Scorecard classification

| **Iron and Folic Acid Supplementation** | **Classification** |
|-----------------------------------------|--------------------|
| \>=95%                                  | Green              |
| 75.0%-94.9%                             | Yellow             |
| \<75%                                   | Red                |

## Terminology note

Refer to the intervention as Iron and Folic Acid supplementation (IFA). Ferrous sulfate, chemically FeSO4, may be used as the iron component of iron supplementation, but the programme indicator should not simply be labelled "FeSO4" because the indicator concerns the combined iron and folic acid supplementation package.

## Important analytical consideration

The raw number receiving IFA may exceed ANC1 in some districts. Do not hide this finding.

Where the resulting percentage exceeds 100%, retain the calculated value and flag it for interpretation. Possible explanations may include differences in how repeat supplementation contacts are reported or the exact routine-data definition of the numerator.

The presentation should distinguish between a mathematically calculated result and its programmatic interpretation.

# 11. Obstetric Ultrasound Scan at ANC

This assesses the proportion of ANC clients documented as having received an obstetric ultrasound scan. The initially considered denominator was total ANC attendance, but the final agreed methodology is to use ANC1.

## Numerator

Number of pregnant women receiving an obstetric ultrasound scan during ANC.

## Denominator

ANC1.

## Formula

**Ultrasound Coverage = Pregnant women receiving obstetric ultrasound / ANC1 x 100**

## Target

**75%**

## Scorecard classification

| **Obstetric Ultrasound Scan at ANC** | **Classification** |
|--------------------------------------|--------------------|
| \>=75%                               | Green              |
| 50.0%-74.9%                          | Yellow             |
| \<50%                                | Red                |

For this analysis, do not use total ANC visits as the denominator. Use ANC1 consistently.

# 12. Teenage Pregnancy

Indicator name: Teenage Pregnancy Among ANC1 Attendees

Two raw age groups are available:

- ANC1 among girls aged below 15 years

- ANC1 among girls aged 15-19 years

These should first be combined.

## Step 1: Calculate total teenage pregnancies

**Teenage ANC1 = ANC1 (\<15 years) + ANC1 (15-19 years)**

## Step 2: Calculate percentage

The denominator is total ANC1.

**Teenage Pregnancy Percentage = \[ANC1 (\<15) + ANC1 (15-19)\] / ANC1 x 100**

Unlike the other indicators, lower performance values are desirable. The objective is to minimise teenage pregnancy.

## Scorecard

| **Teenage pregnancy percentage** | **Classification** |
|----------------------------------|--------------------|
| \<5%                             | Green              |
| 5.0%-12.9%                       | Yellow             |
| \>=13%                           | Red                |

Therefore:

- A low percentage is good.

- A high percentage is poor.

- 13% or higher is red.

Do not apply the normal "higher is better" logic to this indicator. The presentation should clearly identify teenage pregnancy as an inverse indicator.

# 13. Complete Indicator Calculation Matrix

| **Indicator**       | **Numerator**                        | **Denominator**       | **Target**             |
|---------------------|--------------------------------------|-----------------------|------------------------|
| ANC1 coverage       | ANC1                                 | 5% of 2025 population | 95%                    |
| ANC first trimester | ANC1 during first trimester          | ANC1                  | 45%                    |
| ANC4 coverage       | ANC4                                 | 5% of 2025 population | 75%                    |
| ANC8 coverage       | ANC8                                 | 5% of 2025 population | 15%                    |
| IPT3 coverage       | IPT3                                 | 5% of 2025 population | 75%                    |
| Hb testing          | Women tested for Hb                  | ANC1                  | 75%                    |
| Iron & folic acid   | Women receiving \>=30 IFA tablets    | ANC1                  | 95%                    |
| Ultrasound scan     | Women receiving obstetric ultrasound | ANC1                  | 75%                    |
| Teenage pregnancy   | ANC1 \<15 + ANC1 age 15-19           | ANC1                  | \<13%, preferably \<5% |

# 14. Scorecard Threshold Summary

## ANC1 and Iron/Folic Acid

| **Performance** | **Classification** |
|-----------------|--------------------|
| \>=95%          | Green              |
| 75.0%-94.9%     | Yellow             |
| \<75%           | Red                |

## First Trimester ANC

| **Performance** | **Classification** |
|-----------------|--------------------|
| \>=45%          | Green              |
| 30.0%-44.9%     | Yellow             |
| \<30%           | Red                |

## ANC4, IPT3, Hb Testing and Ultrasound

| **Performance** | **Classification** |
|-----------------|--------------------|
| \>=75%          | Green              |
| 50.0%-74.9%     | Yellow             |
| \<50%           | Red                |

## ANC8

| **Performance** | **Classification** |
|-----------------|--------------------|
| \>=15%          | Green              |
| 7.0%-14.9%      | Yellow             |
| \<7%            | Red                |

## Teenage Pregnancy (inverse indicator)

| **Performance** | **Classification** |
|-----------------|--------------------|
| \<5%            | Green              |
| 5.0%-12.9%      | Yellow             |
| \>=13%          | Red                |

# 15. Analytical Approach for the Presentation

Do not simply present tables of percentages. For each indicator, perform four levels of analysis.

## A. Acholi Sub-region Performance

Calculate the overall Acholi percentage using the aggregated numerator and appropriate aggregated denominator. State whether Acholi overall is:

- Meeting the target

- Moderately performing

- Performing poorly

## B. District Comparison

Compare all eight districts and Gulu City. Identify:

- Best performer

- Second-best performer where useful

- Lowest performer

- Districts meeting the target

- Districts in yellow

- Districts in red

## C. Gap Analysis

Where a district is below target, calculate or describe the gap between its performance and the target.

- Example: ANC4 coverage in District X was 58%, which was 17 percentage points below the 75% target.

- Use percentage points when describing differences between percentage performance and targets.

## D. Programmatic Interpretation

Explain what the findings mean operationally.

- High ANC1 but low first-trimester attendance -\> women are accessing ANC, but starting late.

- High ANC1 but low ANC4 -\> poor continuity/retention.

- Reasonable ANC4 but very low ANC8 -\> drop-off before completion of the recommended ANC contact schedule.

- High ANC attendance but low Hb testing -\> quality-of-care/service-readiness problem.

- High ANC1 but low IPT3 -\> missed malaria-in-pregnancy prevention opportunities.

- Low ultrasound coverage -\> limited diagnostic access, equipment availability, referral access or service provision.

- High teenage pregnancy -\> continuing adolescent reproductive-health challenge.

Avoid making causal claims that the data itself cannot prove.

# 16. ANC Continuum of Care

The presentation should include a specific ANC continuum/cascade analysis.

**Expected pregnancies -\> ANC1 -\> First-trimester booking -\> ANC4 -\> ANC8**

This should illustrate where the largest drop-offs occur. A district may have adequate ANC1 coverage but lose women progressively through ANC4 and ANC8.

The analysis should therefore examine not only individual indicators but also the overall pattern of continued ANC utilisation.

**Key analytical question: Are women merely entering ANC, or are they remaining engaged throughout pregnancy?**

# 17. Access Versus Quality Indicators

The indicators should also be conceptually grouped.

## ANC access/utilisation

- ANC1

- ANC4

- ANC8

## Timing

- First-trimester ANC

## Preventive intervention

- IPT3

- Iron and folic acid supplementation

## Quality/diagnostic service

- Hb testing

- Obstetric ultrasound

## Adolescent maternal health

- Teenage pregnancy

This grouping will make the PowerPoint more coherent than presenting nine unrelated indicators.

# 18. Presentation Visualisations

Use clear charts rather than overcrowded tables. Recommended visualisations include:

## Scorecard

Create a district-by-indicator matrix with traffic-light colours: Green, Yellow and Red.

Rows:

- Agago

- Amuru

- Gulu City

- Gulu District

- Kitgum

- Lamwo

- Nwoya

- Omoro

- Pader

- Acholi

Columns:

- ANC1

- First trimester

- ANC4

- ANC8

- IPT3

- Hb testing

- IFA

- Ultrasound

- Teenage pregnancy

## Indicator charts

Use district bar charts with a visible target line. Example: ANC1 Coverage by District - FY 2025/26. Bars represent district percentage and the reference line represents the 95% target. Repeat for relevant indicators.

## ANC continuum chart

Show the progressive pathway from ANC1 -\> ANC4 -\> ANC8. This can reveal attrition in ANC utilisation.

## Teenage pregnancy chart

Rank districts from highest teenage pregnancy percentage to lowest. Since lower is desirable, make this clear in the chart title/subtitle.

# 19. Presentation Narrative

The presentation should tell a story rather than simply report numbers. Suggested sequence:

1\. Title slide

2\. Objective and scope

3\. Data and methodology

4\. 2025 population and estimated pregnancies

5\. Overall Acholi maternal/ANC scorecard

6\. ANC1 coverage

7\. Early ANC initiation/first trimester

8\. ANC4 coverage

9\. ANC8 coverage

10\. ANC continuum of care

11\. IPT3 coverage

12\. Hb testing

13\. Iron and folic acid supplementation

14\. Obstetric ultrasound

15\. Teenage pregnancy

16\. Cross-district comparison

17\. Key gaps

18\. Priority districts

19\. Programmatic interpretation

20\. Recommended actions/conclusion

The exact number of slides can be adjusted according to the amount of information.

# 20. Important Rules for the Analysis

Use the methodology exactly as specified above. Do not independently replace denominators with alternative definitions.

Specifically:

- Use 2025 population, not 2024 or 2026.

- Use 5% of the 2025 population as expected pregnancies.

- Use ANC1 as denominator for first-trimester ANC.

- Use ANC1 as denominator for Hb testing.

- Use ANC1 as denominator for iron and folic acid.

- Use ANC1 as denominator for ultrasound.

- Combine the \<15 and 15-19 ANC1 groups for teenage pregnancy.

- Use ANC1 as denominator for teenage pregnancy.

- Do not cap calculated values at 100%.

- Use the agreed traffic-light thresholds exactly.

- Remember that teenage pregnancy is an inverse indicator.

- Present percentage results to approximately one decimal place.

- Keep raw counts available where useful for interpretation.

- Do not invent explanations unsupported by the data.

# 21. Overall Analytical Question

***How well is the Acholi Sub-region performing across the antenatal care continuum, preventive maternal interventions, quality-of-care services and adolescent pregnancy indicators during FY 2025/26, and which districts require the greatest programmatic attention?***

The analysis should identify both coverage gaps and quality gaps, because good ANC attendance alone does not necessarily mean women are receiving all recommended services.


## AO.2 Intrapartum/newborn methodology snapshot

**ACHOLI SUB-REGION  
INTRAPARTUM PERFORMANCE ANALYSIS**

Methodology and Handover Instructions for FY 2025/26

| **Reporting period**       | July 2025 - June 2026 (FY 2025/26)                                            |
|----------------------------|-------------------------------------------------------------------------------|
| **Population denominator** | 2025 projected population                                                     |
| **Geographic scope**       | Acholi Sub-region districts and Gulu City                                     |
| **Purpose**                | Calculation, scorecard classification, interpretation and PowerPoint handover |

This document captures the agreed intrapartum analysis methodology. The formulas, denominators, targets and scorecard rules below should be used exactly as specified when producing district-level and Acholi aggregate results.

# 1. Purpose and Scope

The analysis will assess institutional delivery, intrapartum/newborn care quality and mortality outcomes across the Acholi Sub-region for FY 2025/26. It should compare districts/city, classify performance using agreed traffic-light thresholds, identify priority gaps and provide concise programmatic interpretation.

## Geographic units to analyse:

- Agago

- Amuru

- Gulu City

- Gulu District

- Kitgum

- Lamwo

- Nwoya

- Omoro

- Pader

- Acholi Sub-region aggregate

# 2. Required Data Elements

The intrapartum analysis uses the following service statistics together with the 2025 projected population:

- Total deliveries in the unit

- Live births

- Caesarean sections

- Proportion of low-birth-weight babies initiated on Kangaroo Mother Care (KMC)

- Babies with birth asphyxia

- Live babies successfully resuscitated

- Fresh stillbirths

- Macerated stillbirths

- Newborn deaths

- Maternal deaths

- 2025 projected population

# 3. General Methodological Rules

- Use the 2025 projected population for population-based denominators.

- Expected deliveries are estimated as 4.85% of the 2025 population.

- Present percentages to one decimal place unless a rate is conventionally shown as a whole number or one decimal place per 1,000 / 100,000.

- Do not cap population-based coverage indicators at 100% automatically, because their denominators are estimated expected populations rather than fixed observed subsets.

- For indicators with a logically fixed/known denominator where the numerator is a subset of that denominator, a result above 100% is not plausible. Code such values BLUE as a data-quality flag and investigate them before interpretation.

- BLUE is a data-quality category, not a performance category. It supersedes the usual green/yellow/red classification when a bounded percentage exceeds 100%.

- Use percentage points when describing the gap between an observed percentage and a percentage target.

- Avoid causal claims that the routine data cannot prove.

# 4. Expected Deliveries Denominator

For institutional delivery coverage, calculate expected deliveries separately for every district/city using:

**Expected deliveries = 2025 population x 0.0485**

This expected-delivery denominator is used only where explicitly specified below.

# 5. Institutional Delivery Coverage

Measures the proportion of expected deliveries that occurred in a health facility / reporting unit during FY 2025/26.

| **Component**              | **Definition**                                                                                |
|----------------------------|-----------------------------------------------------------------------------------------------|
| **Numerator**              | Total number of deliveries in the unit                                                        |
| **Denominator**            | 4.85% of the 2025 projected population                                                        |
| **Formula**                | Institutional delivery coverage (%) = \[Total deliveries / (2025 population x 0.0485)\] x 100 |
| **Target / desired range** | 65% or higher                                                                                 |

## Scorecard classification

| **Performance band** | **Colour** | **Interpretation**                 |
|----------------------|------------|------------------------------------|
| \>=65.0%             | **GREEN**  | Meets or exceeds target            |
| 50.0%-64.9%          | **YELLOW** | Moderate performance; below target |
| \<50.0%              | **RED**    | Poor performance                   |

## Analytical interpretation

- Compare districts against the 65% target and identify where expected deliveries are not being captured institutionally.

- Coverage above 100% should not automatically be treated as impossible because the denominator is an estimated expected-delivery population and may not perfectly match service catchment use.

# 6. Caesarean Section Rate

Measures the proportion of institutional deliveries conducted by Caesarean section. The desired level is a range rather than a one-sided target.

| **Component**              | **Definition**                                                             |
|----------------------------|----------------------------------------------------------------------------|
| **Numerator**              | Number of Caesarean sections                                               |
| **Denominator**            | Total deliveries in the unit                                               |
| **Formula**                | Caesarean section rate (%) = (Caesarean sections / Total deliveries) x 100 |
| **Target / desired range** | Desired range: 5.0% to 15.0%                                               |

## Scorecard classification

| **Performance band** | **Colour**                   | **Interpretation**                                                   |
|----------------------|------------------------------|----------------------------------------------------------------------|
| 5.0%-15.0%           | **GREEN**                    | Within the desired range                                             |
| 3.0%-4.9%            | **YELLOW**                   | Below desired range; possible access/availability concern            |
| 15.1%-20.0%          | **YELLOW**                   | Above desired range; requires review                                 |
| \<3.0%               | **RED**                      | Very low C-section rate                                              |
| \>20.0%              | **RED**                      | Very high C-section rate                                             |
| \>100%               | **BLUE (data-quality flag)** | Numerator cannot logically exceed total deliveries; investigate data |

## Analytical interpretation

- Interpret both very low and very high rates as signals requiring review; the indicator is not a simple higher-is-better measure.

- A value above 100% is mathematically inconsistent for this denominator and must be flagged blue for data-quality review.

# 7. Low-Birth-Weight Babies Initiated on Kangaroo Mother Care

Assesses initiation of Kangaroo Mother Care among eligible low-birth-weight babies. In the supplied dataset this indicator is already expressed as a percentage/proportion and should not be recalculated from other fields unless raw counts are later supplied.

| **Component**              | **Definition**                                                                                                     |
|----------------------------|--------------------------------------------------------------------------------------------------------------------|
| **Numerator**              | Already calculated in the source dataset                                                                           |
| **Denominator**            | Already incorporated in the source percentage                                                                      |
| **Formula**                | Use the supplied percentage directly; round to one decimal place (e.g., 85.51 becomes 85.5%; 83.55 becomes 83.6%). |
| **Target / desired range** | 95% or higher                                                                                                      |

## Scorecard classification

| **Performance band** | **Colour**                   | **Interpretation**                                       |
|----------------------|------------------------------|----------------------------------------------------------|
| 95.0%-100.0%         | **GREEN**                    | Meets or exceeds target                                  |
| 75.0%-94.9%          | **YELLOW**                   | Moderate performance; below target                       |
| \<75.0%              | **RED**                      | Poor performance                                         |
| \>100%               | **BLUE (data-quality flag)** | Not plausible for a bounded proportion; investigate data |

## Analytical interpretation

- This is a quality-of-care indicator for eligible low-birth-weight newborns.

- Do not treat a value above 100% as excellent performance; it is a data-quality problem and should be coded blue.

# 8. Successful Resuscitation of Babies with Birth Asphyxia

Measures the proportion of babies identified with birth asphyxia who were successfully resuscitated.

| **Component**              | **Definition**                                                                                            |
|----------------------------|-----------------------------------------------------------------------------------------------------------|
| **Numerator**              | Number of live babies successfully resuscitated                                                           |
| **Denominator**            | Number of babies with birth asphyxia                                                                      |
| **Formula**                | Successful resuscitation (%) = (Live babies successfully resuscitated / Babies with birth asphyxia) x 100 |
| **Target / desired range** | 90% or higher                                                                                             |

## Scorecard classification

| **Performance band** | **Colour**                   | **Interpretation**                                          |
|----------------------|------------------------------|-------------------------------------------------------------|
| 90.0%-100.0%         | **GREEN**                    | Meets or exceeds target                                     |
| 70.0%-89.9%          | **YELLOW**                   | Moderate performance; below target                          |
| \<70.0%              | **RED**                      | Poor performance                                            |
| \>100%               | **BLUE (data-quality flag)** | Not plausible with this known denominator; investigate data |

## Analytical interpretation

- The denominator is known and the numerator is a subset of babies with birth asphyxia, so the percentage should never exceed 100%.

- Where the denominator is zero, do not calculate a percentage; report as not applicable / no asphyxia cases rather than dividing by zero.

# 9. Perinatal Mortality Rate

Measures perinatal deaths per 1,000 total births using the agreed routine-data definition for this analysis.

| **Component**              | **Definition**                                                                                                                                |
|----------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------|
| **Numerator**              | Fresh stillbirths + Macerated stillbirths + Newborn deaths                                                                                    |
| **Denominator**            | Total births, operationalised here as total deliveries in the unit                                                                            |
| **Formula**                | Perinatal mortality rate per 1,000 total births = \[(Fresh stillbirths + Macerated stillbirths + Newborn deaths) / Total deliveries\] x 1,000 |
| **Target / desired range** | 12 or fewer per 1,000 total births                                                                                                            |

## Scorecard classification

| **Performance band**     | **Colour** | **Interpretation**                       |
|--------------------------|------------|------------------------------------------|
| \<=12.0 per 1,000        | **GREEN**  | Meets target / desirable mortality level |
| \>12.0 to 20.0 per 1,000 | **YELLOW** | Elevated mortality                       |
| \>20.0 per 1,000         | **RED**    | High mortality; priority concern         |

## Analytical interpretation

- This is an inverse indicator: lower is better.

- State the unit explicitly as deaths per 1,000 total births, not percent.

- Use total deliveries as the operational denominator for total births in this analysis, as agreed.

# 10. Fresh Stillbirth Rate

A quality-of-care indicator intended to signal possible problems around labour and intrapartum care. Any interpretation of causation should remain cautious because the routine data alone cannot establish why a fresh stillbirth occurred.

| **Component**              | **Definition**                                                                              |
|----------------------------|---------------------------------------------------------------------------------------------|
| **Numerator**              | Fresh stillbirths                                                                           |
| **Denominator**            | Total deliveries in the unit                                                                |
| **Formula**                | Fresh stillbirth rate per 1,000 deliveries = (Fresh stillbirths / Total deliveries) x 1,000 |
| **Target / desired range** | 5 or fewer per 1,000 deliveries                                                             |

## Scorecard classification

| **Performance band**    | **Colour** | **Interpretation**                           |
|-------------------------|------------|----------------------------------------------|
| \<=5.0 per 1,000        | **GREEN**  | Meets target / desirable level               |
| \>5.0 to 10.0 per 1,000 | **YELLOW** | Elevated fresh stillbirth rate               |
| \>10.0 per 1,000        | **RED**    | High fresh stillbirth rate; priority concern |

## Analytical interpretation

- This is an inverse indicator: lower is better.

- Describe fresh stillbirths as a potential intrapartum quality signal rather than asserting that every fresh stillbirth was caused by poor care.

# 11. Maternal Mortality Ratio (MMR)

Measures maternal deaths per 100,000 live births.

| **Component**              | **Definition**                                                          |
|----------------------------|-------------------------------------------------------------------------|
| **Numerator**              | Total maternal deaths                                                   |
| **Denominator**            | Total live births                                                       |
| **Formula**                | MMR per 100,000 live births = (Maternal deaths / Live births) x 100,000 |
| **Target / desired range** | 183 or fewer per 100,000 live births                                    |

## Scorecard classification

| **Performance band** | **Colour** | **Interpretation**                        |
|----------------------|------------|-------------------------------------------|
| \<=183 per 100,000   | **GREEN**  | Meets target / desirable level            |
| 184-300 per 100,000  | **YELLOW** | Elevated maternal mortality               |
| \>300 per 100,000    | **RED**    | High maternal mortality; priority concern |

## Analytical interpretation

- This is an inverse indicator: lower is better.

- Because maternal deaths are relatively rare, district-level ratios can fluctuate considerably when the number of live births is small. Present the underlying maternal-death count alongside the ratio where useful.

# 12. Complete Indicator Calculation Matrix

| **Indicator**                   | **Numerator**                            | **Denominator**                 | **Scale**    | **Target / desired range** |
|---------------------------------|------------------------------------------|---------------------------------|--------------|----------------------------|
| Institutional delivery coverage | Total deliveries                         | 4.85% of 2025 population        | x100         | \>=65%                     |
| Caesarean section rate          | Caesarean sections                       | Total deliveries                | x100         | 5%-15%                     |
| LBW babies initiated on KMC     | Pre-calculated percentage                | Already incorporated            | Use as given | \>=95%                     |
| Successful resuscitation        | Successfully resuscitated babies         | Babies with birth asphyxia      | x100         | \>=90%                     |
| Perinatal mortality rate        | Fresh SB + Macerated SB + Newborn deaths | Total deliveries / total births | x1,000       | \<=12/1,000                |
| Fresh stillbirth rate           | Fresh stillbirths                        | Total deliveries                | x1,000       | \<=5/1,000                 |
| Maternal mortality ratio        | Maternal deaths                          | Live births                     | x100,000     | \<=183/100,000             |

# 13. Scorecard Threshold Summary

| **Indicator**            | **GREEN**      | **YELLOW**           | **RED**       | **BLUE data-quality** |
|--------------------------|----------------|----------------------|---------------|-----------------------|
| Institutional deliveries | \>=65%         | 50%-64.9%            | \<50%         | \-                    |
| Caesarean sections       | 5%-15%         | 3%-4.9% OR 15.1%-20% | \<3% OR \>20% | \>100%                |
| KMC initiation           | 95%-100%       | 75%-94.9%            | \<75%         | \>100%                |
| Successful resuscitation | 90%-100%       | 70%-89.9%            | \<70%         | \>100%                |
| Perinatal mortality      | \<=12/1,000    | \>12-20/1,000        | \>20/1,000    | \-                    |
| Fresh stillbirth rate    | \<=5/1,000     | \>5-10/1,000         | \>10/1,000    | \-                    |
| MMR                      | \<=183/100,000 | 184-300/100,000      | \>300/100,000 | \-                    |

# 14. Analytical Approach for the Presentation

## A. Acholi aggregate performance

- Calculate the Acholi aggregate using aggregated numerators and the correct aggregated denominator.

- State whether the sub-region is green, yellow, red or blue for each indicator.

## B. District comparison

- Compare all eight districts and Gulu City.

- Identify best and worst performers, districts meeting target, and districts requiring priority action.

## C. Gap analysis

- For percentage indicators, describe the gap from target in percentage points.

- For mortality/rate indicators, describe the excess above the agreed threshold in the relevant rate units.

## D. Quality and data-quality interpretation

- Separate true performance concerns from implausible values.

- Any bounded percentage above 100% should be shown in blue and discussed as a data-quality issue, not celebrated as overachievement.

## E. Programmatic interpretation

- Institutional delivery gaps may indicate limited service use or access barriers.

- Very low C-section rates may point to access/referral/capacity concerns, while very high rates warrant review of case mix and practice patterns.

- Low KMC initiation or resuscitation success reflects newborn-care quality gaps.

- High perinatal mortality, fresh stillbirth rate or MMR should be treated as priority outcomes requiring review of service quality, referral pathways, emergency readiness and case review processes.

# 15. Recommended PowerPoint Visualisations

- Overall district-by-indicator scorecard using GREEN, YELLOW, RED and BLUE.

- Institutional delivery bar chart with a 65% target line.

- Caesarean section chart with a shaded desired band from 5% to 15% rather than a single target line.

- KMC and successful-resuscitation district charts with target lines and blue flags for any value above 100%.

- Perinatal mortality and fresh stillbirth rate charts ranked from highest to lowest, with target threshold lines.

- MMR chart with the 183 per 100,000 target line; show maternal-death counts as labels or in a companion table where practical.

- A final priority matrix showing districts with multiple red indicators and any blue data-quality flags.

# 16. Suggested Presentation Narrative

1\. Title and purpose

2\. Data sources and agreed methodology

3\. 2025 population and expected deliveries

4\. Overall intrapartum scorecard

5\. Institutional delivery coverage

6\. Caesarean section rate

7\. KMC initiation among low-birth-weight babies

8\. Successful resuscitation of birth asphyxia

9\. Perinatal mortality rate

10\. Fresh stillbirth rate

11\. Maternal mortality ratio

12\. Cross-district comparison and priority districts

13\. Data-quality flags and interpretation

14\. Key programmatic gaps

15\. Recommended actions and conclusion

# 17. Non-Negotiable Instructions for Analysis

- Use 2025 projected population.

- Use 4.85% of 2025 population as expected deliveries for institutional delivery coverage.

- Use total deliveries as the denominator for Caesarean section rate and fresh stillbirth rate.

- Use the supplied KMC proportion directly and round it to one decimal place.

- Use babies with birth asphyxia as the denominator for successful resuscitation.

- Calculate perinatal deaths as fresh stillbirths + macerated stillbirths + newborn deaths.

- Calculate perinatal mortality per 1,000 total births, operationalised here using total deliveries as agreed.

- Calculate MMR using maternal deaths / live births x 100,000.

- Do not convert mortality rates to percentages.

- Apply the exact scorecard thresholds in this document.

- For bounded indicators with a known denominator, classify values above 100% as BLUE for data-quality review.

- Do not invent alternative denominators, targets or explanations.

# 18. Overall Analytical Question

**How well is the Acholi Sub-region performing in institutional delivery coverage, operative obstetric care, immediate newborn care and intrapartum maternal/perinatal outcomes during FY 2025/26, and which districts require the greatest programmatic or data-quality attention?**

**Handover note:** This methodology was agreed through discussion and is intended to be used as the calculation and interpretation specification for the intrapartum PowerPoint analysis. Any later methodological changes should be explicitly agreed before replacing these rules.


## AO.3 EPI target-population source snapshot

| **Vaccine**                                  | DISEASE                                                                                                                                                      | Age                              | Target population |
|----------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------|----------------------------------|-------------------|
| **BCG**                                      | Tuberclosis                                                                                                                                                  | At birth                         | 4.85%             |
| **OPV O (Oral polio vaccine)**               | Poliomyelitis                                                                                                                                                | At birth                         | 4.85%             |
| **Hep B birth dose**                         | Hepatitis B infection                                                                                                                                        | At birth                         | 4.85%             |
| **OPV1**                                     | Poliomyelitis                                                                                                                                                | At 6 weeks                       | 4.3%              |
| **DPT-HepB- Hib1 PCV1**                      | a combination vaccine that protects against five serious diseases: diphtheria, tetanus, whooping cough, hepatitis B, and Haemophilus influenzae type B (Hib) | At 6 weeks                       | 4.3%              |
| **RotaV1**                                   | Rotavirus infections                                                                                                                                         | At 6 weeks                       | 4.3%              |
| **PCV 1**                                    | Pneumonia                                                                                                                                                    | At 6 weeks                       | 4.3%              |
| **IPV 1 (Inactive polio vaccine)**           | Poliomyelitis                                                                                                                                                | At 6 weeks                       | 4.3%              |
| **OPV2**                                     | Poliomyelitis                                                                                                                                                | At 10 Weeks                      | 4.3%              |
| **Malaria**                                  | Malaria                                                                                                                                                      | 6 months                         | 4.3%              |
| **Malaria 2**                                | Malaria                                                                                                                                                      | 7 months                         | 4.3%              |
| **Malaria 3**                                | Malaria                                                                                                                                                      | 8 months                         | 4.3%              |
| **DPT-HepB- Hib2**                           | a combination vaccine that protects against five serious diseases: diphtheria, tetanus, whooping cough, hepatitis B, and Haemophilus influenzae type B (Hib) | At 10 Weeks                      | 4.3%              |
| **PCV 2**                                    | Pneumonia                                                                                                                                                    | At 10 Weeks                      | 4.3%              |
| **RotaV 2**                                  | Rotavirus infections                                                                                                                                         | At 10 Weeks                      | 4.3%              |
| **OPV3**                                     | Poliomyelitis                                                                                                                                                | At 14 weeks                      | 4.3%              |
| **DPT-HepB- Hib3 PCV3**                      | a combination vaccine that protects against five serious diseases: diphtheria, tetanus, whooping cough, hepatitis B, and Haemophilus influenzae type B (Hib) | At 14 weeks                      | 4.3%              |
| **IPV 2**                                    | Poliomyelitis                                                                                                                                                | At 14 weeks                      | 4.3%              |
| **PCV3**                                     | Pneumonia                                                                                                                                                    | At 14 weeks                      | 4.3%              |
| **Measles Rubella**                          | Measles and Rubella                                                                                                                                          | 9 Months                         | 4.3%              |
| **Yellow Fever vaccine**                     | Yellow Fever                                                                                                                                                 | 9 Months                         | 4.3%              |
| **Tetanus Toxiod diphtheria (Td) (5 doses)** |  tetanus toxoid-diphtheria (Td) vaccine is recommended for women of childbearing age to protect against tetanus and diphtheria                               | 15- 49 yrs. (WCBA)               | 23%               |
| **HPV Vaccination**                          | Human papillomavirus (HPV)                                                                                                                                   | 10 Yrs. & at 10 ½ Yrs. for girls | 1.53%             |
| **Vit A 100,000 IU**                         |                                                                                                                                                              | 6 - 11 months                    | 1.93%             |
| **Vitamin A (200,000 I.U)/ Deworming**       |                                                                                                                                                              | 12-59 months                     | 16.20%            |
| **Dewormers**                                |                                                                                                                                                              | 1-14 years                       | 49.30%            |
| **Under 5**                                  |                                                                                                                                                              |                                  | 20.50%            |

TO get performance of a facility or district regarding any indicator we = doses administered divided by (target population \* UBOS estimates)

The UBOS estimate is annual so if we are calculating performace of a month we divide by 12 and if it is for 3 months we divide by 12 and multiply by 3 to get the estimate for 3 months. So if we are getting performance for October to December and the annual UBOS estimate is 12000 then the UBOS estimate for that period is 3000.

I am going to share vaccines doses in different periods of different facilities in Pader district and you will give performance of different facilities, anomalies and


# Appendix AP. Final Handoff Rule

This file should be treated as living configuration context, not as a substitute for code-level tests. Every formula, population rule, threshold, status rule and export behaviour must ultimately exist in machine-readable configuration and automated tests. When the implementation diverges from this document, either the implementation is wrong or the document must be explicitly updated through a recorded decision. Silent divergence is not acceptable.


# Appendix AQ. Source Asset Inventory and Handling Rules

The following artifacts were used during the design and analytical work. File names are listed so the IDE can recognise them if the user uploads them again. Raw values in sensitive line lists must not be committed to a public repository or forwarded to third-party AI services.

## AQ.1 Methodology and population references

- `Acholi_ANC_Performance_Analysis_Methodology_FY2025_26.docx`
- `Acholi_Intrapartum_Performance_Analysis_Methodology_FY2025_26.docx`
- `EPI(1).docx`
- `Acholi_Population_2024_and_Projections.xlsx`

## AQ.2 Aggregate analytical datasets used as fixtures

- `ANC 2024 2025.xls`
- `INTRAPARTUM.xls`
- `intrapartum 2024 2025.xls`
- `PERINATAL AND MATERNAL DEATHS REPORTED.xls`
- `MPDSR TREND.xls`

## AQ.3 Sensitive event/line-list sources

- `PERINATAL DEATHS NOTIFIED LIST.xls`
- `PERINATAL DEATH REVIEW LIST.xls`
- `MATERNAL DEATH NOTIFICATION LIST.xls`
- `MATERNAL DEATH REVIEW LINE LIST.xls`

These files may contain event-level health information. They should be used only in authorised development/test environments, with least-privilege access and appropriate de-identification. Production automated tests should prefer synthetic fixtures that reproduce the relevant structural edge cases rather than storing sensitive source rows.

## AQ.4 Presentation outputs used as analytical/visual references

- `ANC_Comparison_Acholi_FY2024_25_vs_FY2025_26.pptx`
- `ANC_Scorecard_Acholi_FY2025_26.pptx`
- `Intrapartum_Comparison_Acholi_FY2024_25_vs_FY2025_26.pptx`
- `Intrapartum_Scorecard_Acholi_FY2025_26.pptx`
- `MPDSR_Trends_and_Hotspots_Acholi_FY2025_26.pptx`
- `MPDSR_Perinatal_and_Maternal_Acholi_FY2025_26.pptx`
- `Maternal_MPDSR_Acholi_FY2025_26.pptx`

The final platform should not depend on these files at runtime. Their role is to inform templates and regression expectations.

# Appendix AR. Saved Views, Shareable State and Presentation Mode

## AR.1 URL/state model

The selected analytical state should be serialisable in the URL or a saved-view record, for example conceptually:

`/dashboard?orgUnit=PADER&period=FY2025_26&programme=MNCH&view=scorecard`

Changing URL parameters must never bypass server-side permission checks.

## AR.2 Saved analytical views

Users should be able to save authorised combinations of geography, period, programme, indicators and preferred visual state, such as `Pader Monthly MNCH Review` or `Acholi MPDSR Review`. Saved views improve recurring meeting workflows and should store configuration, not copies of sensitive raw data.

## AR.3 Performance-review / presentation mode

A useful later feature is `Generate Performance Review`. The user selects geography, period, comparison period and modules, and the publishing engine assembles an approved PowerPoint sequence. Example for Acholi MNCH:

1. Title / scope
2. Executive overview
3. ANC scorecard
4. ANC year comparison
5. Intrapartum/newborn scorecard
6. Mortality trends/hotspots
7. MPDSR notification/review scorecard
8. Perinatal deep dive
9. Maternal deep dive
10. Priority actions

The slide order must be template-driven. AI may provide bounded narrative, but it does not choose arbitrary unapproved layouts.

# Appendix AS. Refresh, Alerts and Performance Surveillance Roadmap

The product should evolve from passive dashboarding to active performance surveillance. Scheduled DHIS2 synchronisation and recalculation can detect meaningful changes without requiring manual Excel extraction.

Potential alert classes include:

- reporting completeness/timeliness deterioration
- new maternal/perinatal event remaining ACTIVE beyond expected workflow window
- indicator crossing a red threshold
- bounded value >100%
- abrupt monthly spike/drop
- unusual zero
- reconciliation gap between aggregate and event data
- sustained deterioration over multiple periods
- metadata mapping failure
- stale analytics tables

Alerts must contain the evidence and reason for firing. Notifications through email/SMS/other channels can be a later integration and should respect permissions and sensitivity.

# Appendix AT. Final IDE Start Checklist

Before the first coding prompt is executed, the IDE should be able to answer all of the following from this handoff without asking the user to repeat information:

1. What is the product and what problem does it solve?
2. What is the first production programme scope?
3. What is the highest-authorised-level landing rule?
4. What are the three permission dimensions?
5. What is the geography hierarchy?
6. What is the FY population-year rule?
7. How are missing facility populations handled?
8. Which indicators use 5%, 4.85%, 4.3% and other target coefficients?
9. What are the ANC formulas and thresholds?
10. What are the intrapartum/newborn formulas and thresholds?
11. What is BLUE and when is it used?
12. What are the perinatal and maternal MPDSR targets?
13. How is notification timeliness currently operationalised?
14. How is review timeliness calculated?
15. How are ACTIVE events treated?
16. Why can a true case-level funnel be invalid without a shared identifier?
17. Which DHIS2 APIs serve aggregate analytics, event analytics and current Tracker state?
18. What is the approved blue/DHIS2-like UI direction?
19. Which screens are mandatory, including the district facility-comparison screen?
20. What work is deterministic and what work may use AI?
21. What information must never be sent to an external AI by default?
22. How are Excel, PowerPoint and narrative reports generated reproducibly?
23. What are the gold-standard Acholi regression fixtures?
24. What production inputs are still TBD?
25. What are the seven phases and twenty-six implementation prompts?

If the IDE cannot answer these, it has not read enough of the handoff to start safely.

# Appendix AU. Approved Presentation Template Contracts and Latest Slide Decisions

The platform's PowerPoint generator should reproduce approved analytical structures rather than inventing new layouts. The following contracts capture the latest presentation-specific decisions made during the manual analysis.

## AU.1 General scorecard slide rules

- Use grouped indicator headers where multiple periods or process stages are shown.
- Use `Target`, not `Benchmark`, as the target-row label in the final MPDSR scorecard.
- Leave count-column target cells blank. Do not insert decorative dashes under `Reported`, `Notified` or `Reviewed`.
- Apply RAG/BLUE fills only to indicator/performance cells, not to raw count cells.
- Keep the aggregate row visually distinct and bold.
- Use plain, simple English in the finding panel.
- Do not create an AI-looking presentation with floating decorative KPI boxes, excessive rounded cards or large empty spaces.
- Keep footnotes small but readable and use them for important denominator/timeliness caveats.

## AU.2 ANC year-on-year comparison template

The comparison slide should use the same district/city rows for both years and place FY2024/25 and FY2025/26 side by side under each indicator or in a consistent grouped structure. The engine must use 2024 population for FY2024/25 and 2025 population for FY2025/26. The slide may include concise findings, but the table is the primary evidence.

Important analytical behaviours:

- preserve values above 100% when they are mathematically produced from expected-population denominators;
- flag extreme IFA >100% as a data-definition/reporting concern rather than silently correcting it;
- compute Acholi from aggregate counts;
- show percentage-point change for percentage indicators;
- do not average district percentages.

## AU.3 Intrapartum year-on-year comparison template

Recommended split is two slides:

1. Delivery Access & Immediate Newborn Care
   - Institutional delivery
   - C-section rate
   - KMC
   - Successful resuscitation

2. Maternal & Perinatal Outcomes
   - PMR
   - Fresh stillbirth rate
   - MMR

Show FY2024/25 and FY2025/26 side by side. BLUE values remain BLUE and must not be described as improvement. Mortality values display their rate units, not `%`.

## AU.4 Mortality trends and hotspot template

A strong two-slide analytical sequence was developed from the MPDSR monthly data:

### Slide A - Temporal trends

- stacked monthly columns for fresh stillbirths, macerated stillbirths and newborn deaths;
- maternal deaths overlaid as a line on a separate axis;
- annotation of the August perinatal peak and April-May maternal-death peak;
- optional quarterly composition chart showing the shift toward newborn deaths.

### Slide B - Geographic concentration

- scatter/dot plot comparing share of institutional deliveries with share of perinatal deaths;
- equality/reference line;
- Gulu City callout showing its disproportionate share of recorded burden;
- compact maternal-death heatmap by district and month;
- cautious referral/case-mix note.

Monthly MPDSR trend visuals should show counts when monthly denominators are unavailable. Never manufacture monthly mortality rates from annual denominators.

## AU.5 Final MPDSR four-slide template

The final focused MPDSR presentation structure is:

### Slide 1 - MPDSR Notification & Review Performance

One combined table for perinatal **and** maternal deaths.

Perinatal columns:

- Reported
- Notified
- % Notified
- % Notified on time
- Reviewed
- % Reviewed
- % Reviewed on time

Maternal columns:

- Reported
- Notified
- % Notified
- % Notified on time
- Reviewed
- % Reviewed
- % Reviewed on time

Use the agreed perinatal and maternal colour bands. `Target` row only contains target values under percentage columns. Counts remain neutral.

The first key finding should mention maternal notification timing data quality where relevant. Pader's perinatal line-list/reported mismatch should be explicit and BLUE. It is appropriate to state that the district should reconcile records, check possible duplicates/under-reporting and ensure all confirmed perinatal deaths are reported; the system itself should not decide which explanation is true without record-level evidence.

### Slide 2 - Perinatal MPDSR Process Performance & Data Quality

The quarterly process chart is the main visual and must be large and readable. Quarter labels include months:

- Q1 Jul-Sep
- Q2 Oct-Dec
- Q3 Jan-Mar
- Q4 Apr-Jun

Plot notification coverage, timely notification, review coverage and timely review with a visible 90% target line. Add direct labels and a small number of meaningful annotations. Include August as a pressure point, active events and specific facility-level documentation/date-quality findings where appropriate.

### Slide 3 - Perinatal Death Causes & Documentation

Use horizontal bar charts rather than pie charts because causes can overlap. Show separate or small-multiple views for neonatal deaths, fresh stillbirths and macerated stillbirths. Include the trend in missing cause documentation, the high use of `Other`/`Unknown`, and facility-specific documentation follow-up examples. Analyse recurring themes in `Other` cautiously as free-text themes, not official mutually exclusive causes.

### Slide 4 - Maternal Death MPDSR Deep Dive

Use a clean process chart instead of mechanical floating KPI boxes. Show notification coverage, timely notification, completed review and reviewed within seven days against the 100% target. Label active reviews as `Active reviews (not completed)`.

Also show:

- structured maternal cause mentions;
- documented delay factors;
- facility stay before death;
- structured cause documentation completeness;
- limited facility-specific documentation signals with counts and percentages;
- simple-English key findings.

Do not use the word `provisional` on final submission slides. The production data model must nevertheless ensure that the correct review-stage date field has been mapped before the metric is considered valid.

## AU.6 Narrative style for generated slides

The user wants the slides to sound like a human public-health/biostatistics team prepared them. Avoid obvious AI phrasing, excessive section labels and decorative prose. Findings should be concise, specific and numerical. Prefer standard punctuation and straightforward sentences. The platform should not insert phrases such as `this highlights the importance of` when a more direct statement is available.


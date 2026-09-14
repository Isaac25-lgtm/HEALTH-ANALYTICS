# Implementation Roadmap

## Status and phase gates

**Current status: PHASES 1–7 CODE EXISTS / CORRECTIVE PASS VERIFIED LOCALLY / NOT A LIVE GO-LIVE.** Persistent snapshots, exact-run AI/exports, independent fixtures, MapLibre maps, and disposable PostgreSQL 18 migration/concurrency gates are implemented. Live DHIS2, official templates, owner populations, Redis production topology, and identity remain pending.

| Phase | Planned prompts | Gate |
|---|---:|---|
| 1. Architecture and Foundations | 1–3 | **Gate passed (2026-09-12).** Explicit Alembic history, cookie/CSRF sessions, and server-side authorisation verified by the current full suite. |
| 2. Data and Calculation Engines | 4–8 | **Gate passed (2026-09-12).** Mocked connector contracts, geography/population, calculation and quality engines verified, including disposable PostgreSQL 18 migrations. Live DHIS2 verification pending. |
| 3. MNCH Analytical Modules | 9–12 | **Gate passed (2026-09-12).** See `docs/architecture/PHASE3_COMPLETION.md`. |
| 4. Dashboard Experience | 13–18 | **Gate passed (2026-09-12).** See `docs/architecture/PHASE4_COMPLETION.md`. |
| 5. AI Intelligence | 19–20 | **Implemented (2026-09-12).** See `docs/architecture/PHASE5_COMPLETION.md`. |
| 6. Publishing | 21–23 | **Implemented (2026-09-12).** Platform-default templates. See `docs/architecture/PHASE6_COMPLETION.md`. |
| 7. Hardening and Production | 24–26 | **Implemented for audit (2026-09-12).** Not a live go-live. See `docs/architecture/PHASE7_COMPLETION.md`. |

## Planned prompt sequence

1. Master Application Architecture  
2. Database and Domain Model  
3. Authentication and Authorisation  
4. DHIS2 Aggregate Connector  
5. DHIS2 Event and Tracker Connector  
6. National Geography and Population Engine  
7. Indicator Calculation Engine  
8. Data Quality Engine  
9. ANC Module  
10. Intrapartum and Newborn Module  
11. Immunization and Child Health Module  
12. MPDSR Module  
13. Global UI Design System  
14. National Dashboard  
15. Regional Dashboard  
16. District Facility Performance Dashboard  
17. Individual Facility Dashboard  
18. Maps and Geographic Intelligence  
19. AI Gateway  
20. AI Analyst and Ask the Data  
21. Excel Generator  
22. PowerPoint Generator  
23. Narrative Report Generator  
24. Full Regression and Validation  
25. Security, Performance and Reliability  
26. Production Deployment and Documentation

Every prompt must restate relevant canonical context, produce automated evidence appropriate to its scope, and avoid consuming unapproved production inputs. The canonical handoff’s Appendix F contains detailed prompt contracts; Appendix J is a broader 30-item acceptance matrix, not a competing roadmap.

Phase implementation notes live in `docs/architecture/`. Phases 5–7 were completed under the 2026-09-12 owner instruction to finish remaining phases for later audit.

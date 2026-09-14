# Uganda Health Performance Intelligence Platform — Working Instructions

This repository has **Phases 1–7 implemented** under the owner instruction of 2026-09-12 to complete remaining phases for later audit. Do not begin a live production go-live or invent DHIS2/population/template inputs.

The owner authorised Phase 1/2 closure plus complete Phase 3 and Phase 4 on 2026-09-12, and subsequently authorised Phases 5 (AI), 6 (publishing), and 7 (hardening/production documentation).

Before a material architecture, calculation, integration, UI, AI, export, or security change:

1. Read `ULTIMATE_IDE_HANDOFF_Uganda_Health_Performance_Intelligence_Platform.md` and the relevant `docs/project-context/` file.
2. Preserve deterministic, versioned calculation: the computer calculates; AI interprets verified evidence; publishing formats.
3. Enforce geography, programme, and action permissions on the server. URL or UI state must not expand access.
4. Preserve the blue/navy, compact DHIS2-like visual contract and extremely subtle natural background.
5. Do not invent public-health rules, thresholds, DHIS2 UIDs, population values, mappings, or credentials; record gaps in `docs/project-context/OPEN_ITEMS.md`.
6. Minimise sensitive MPDSR data; never send raw identifying line lists to external AI by default.
7. Keep values traceable to source, formula version, population version, and calculation run. Never silently cap invalid values or turn missing into zero.
8. Update context documents after approved implementation and run relevant regression, permission, and calculation tests.

The canonical handoff is authoritative except where a later explicit project-owner instruction supersedes it.

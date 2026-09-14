# Open Production Inputs

Do not invent any item in this register. Each requires a project-owner, Ministry/programme, or authorised technical decision before production configuration.

| Area | Required input | Why it is needed |
|---|---|---|
| DHIS2 connectivity | Confirmed production base URL, authentication/session method, credential/secrets approach, network access, and refresh policy | Safe live connector configuration |
| DHIS2 metadata | Org-unit UIDs, aggregate data-element/indicator and category mappings, MPDSR program/stage/field semantic mappings, metadata access validation | Correct extraction and calculation |
| Geography | Approved analytical hierarchy, current/historical org-unit mappings, city/sub-county treatment, boundary effective date, and owner approval of the supplied boundary files | Complete, unambiguous geometry import and map drill-down |
| Population | Approved population files, source/version/validity rules, all required years, official facility catchment values, and facility override approval workflow | Population denominators and reproducibility |
| EPI governance | Authoritative indicator bands/targets not yet specified, plus relevant timeliness/continuum definitions | RAG classification without invention |
| Indicator governance | Any additional MNCH definitions, mapping exceptions, direct-percent contracts, valid-from/to dates, and approved methodology owners | Registry completion |
| MPDSR data contract | Exact date fields for death, notification, and review; event linkage/shared identifier; cause taxonomy; sensitive-data access and retention policy | Correct cohorts, timeliness, privacy |
| Users/security | Identity provider, roles, initial geography/programme/action grants, exact retention durations and purge-approval policy, admin separation | Safe authn/authz. D-041 establishes the minimal control/provenance-store boundary but intentionally does not invent retention durations. |
| Publishing | Approved official MoH logo asset; Excel, national/regional/district/facility/MPDSR PowerPoint and report templates; export retention | Professional governed outputs |
| AI | Approved provider/model(s), data-processing approval, cost/token limits, redaction policy, evidence schema, no-AI fallback | Safe bounded AI |
| Operations | Hosting, database, job queue, cache, monitoring, backup/restore, SLAs, alert channels and cadence | Production reliability |
| Local PostgreSQL credentials | Confirm the intended database/user name for the owner-supplied internal PostgreSQL password and whether the existing port-5432 instance is a disposable development target | The 2026-09-12 migration gate used a newly created isolated PostgreSQL 18.1 cluster with trust authentication on port 55432. The existing localhost:5432/5433 instances were not mutated and no password was written to the repository. |
| Playwright Chromium binary | Network access to `cdn.playwright.dev`, or an approved browser cache | `npx playwright install chromium` failed with DNS `ENOENT cdn.playwright.dev`. System Chrome exists but Playwright launch did not complete in this session. |
| Phase 5–7 inputs | Approved AI provider/model and processing agreement; official MoH publishing templates; production hosting, Redis, monitoring, and PostgreSQL backup | Platform fallbacks exist. These inputs are still required before a production go-live. |
| Corrective snapshot operations | Redis-backed export/AI workers in the owner-approved topology, production query SLA, and map tile hosting if a basemap is required | Exact-run snapshot IDs are required. MapLibre renders owner geometry without a third-party basemap. Test/dev export generation may still be eager. |

## Open inputs raised by the 2026-09-13 material amendment

Implemented defaults below are fail-closed. None is an owner decision until accepted.

| Area | Required input | Current implemented behaviour |
|---|---|---|
| Base corrective prompt | The amendment supplements a corrective prompt that was not received in this session | Only the 17 amendment sections were implemented. Defects that exist only in the unreceived prompt are not addressed. |
| Sub-annual population year (§4) | An explicit rule for months, quarters and half-years (calendar-year base, FY base year, or programme-specific) | No rule was found. The workbook guide states calendar-year and financial-year rules only. Existing FY rules apply to full financial years (`applies_to_period_kinds=["fy"]`). Population-derived values for other period kinds return `population_rule_missing` until an approved `PeriodPopulationRule` names those kinds. |
| Calendar-year population rule | Approval of the workbook guide's "calendar year N uses year N" rule | Not seeded. Calendar-year periods return `population_rule_missing`. |
| Population workbook (§2/§3) | Approved national organisation-unit hierarchy; recorded alias decisions; owner approval of the imported draft versions | Workbook verified unchanged: SHA-256 `5AE43DCA4533347FBB95C3F9B4E08A25C953C90905445614BA7D4E4BD3E75072`, 146 units (135 districts, 11 cities), 2024–2030, 1,022 cells, NATIONAL TOTAL equals the unit sum, Acholi N.5 totals 2,044,355 / 2,152,700 reproduced. Dry run against the synthetic seed: 3 exact matches (Pader, Kitgum, Soroti), 143 blocking. **No import was performed.** |
| Population aliases | Decisions for `Kampala Capital City` ↔ the hierarchy's Kampala unit, `Gulu` ↔ Gulu District, and `Manafwa` ↔ Manafa if the hierarchy uses that spelling | Exact normalised name + unit type only. No fuzzy matching. An alias needs a proposal and a decision by a different `approve_population` user (system administrators excepted), both audited. |
| MPDSR sync window (§6) | Whether the Tracker `occurredAt` date is the death date or the report date; the approved follow-up window for completion counts | A zero is verified only by a successful, complete, non-truncated, current Tracker job whose window starts on or before the cohort start and ends on or after the follow-up end (notification +1 day, review +7 days) or the extraction date for counts. Operators pass `event_window_end` (Tracker jobs only, between the period end and today). Staleness uses `DHIS2_STALE_HOURS` (72). |
| MPDSR cause disclosure (§10) | Approved minimum cell count and disclosure levels | `MPDSR_CAUSE_MIN_CELL_COUNT` is unset, so cause patterns are withheld everywhere. When set, disclosure is limited to country/region/sub-region, requires MPDSR programme scope plus `view_mpdsr_events`, counts structured categories only, and suppresses categories below the minimum or reported by a single unit. |
| Region/sub-region boundaries (§13) | Approved region or sub-region geometry, if national maps are required | National maps report `geometry_unavailable_for_level`. District polygons are never substituted for regions. |
| Ranking defaults (§9) | Owner confirmation of the platform defaults | Five best and five worst units; ties broken by name; PMR, fresh stillbirth rate, MMR and all MPDSR indicators are never ranked; unclassified (TBD) indicators are never ranked. |
| AI evidence size | Confirmation of the 20,000-character provider limit | An oversized package no longer blocks the user: the external provider is skipped (`evidence_exceeds_provider_limit`) and the local deterministic answer is returned. Evidence rows omit unrecorded fields and repeated quality flags are grouped with an occurrence count. |
| Frontend build directory ACLs | Removal of `frontend/.next-gate` by an administrator, or ACL reset | The existing `.next-gate` artifacts were created by another sandbox identity. The current user lacks Delete rights, and Next.js 15.5.25 `recursiveDelete` retries `EPERM` indefinitely (`t++` passes the unchanged counter), so `next build` hangs silently after the version banner. The build was verified on an isolated scratch copy instead. |
| Playwright in the project directory | The `.next-gate` ACL fix above | Playwright ran 5/5 against the e2e API (port 8010) and a production build of an isolated scratch copy of the frontend. Its configured `next build` web-server step would hang in the project directory until `.next-gate` is removable. Two pre-existing ambiguous selectors in the spec were tightened. |
| Items outside the amendment | Export worker dispatch topology, Celery/Redis in the API image, future formula fallback, CI PostgreSQL/Playwright portability, visual reskin | Left unchanged. |

## GeoJSON facts to preserve

- `UGANDA_DISTRICT.json`: 146 valid district features.
- `UGANDA_SUBCOUNTIES.json`: 2,190 valid sub-county features.
- `UGANDA_DISTRICTS.json`: alternate Esri JSON.
- Synthetic seed dry run: district 3/146 name-matched; sub-county 0/2,190 matched. Expected because the approved national hierarchy is absent. Do not apply fuzzy guesses.

## Clarifications to preserve

- No production performance values, MoH UIDs, or credentials are present in this workspace. The owner-supplied district/city population workbook is present as a candidate source (see the amendment table above); it has not been imported or approved, and it never supplies facility or sub-county populations.
- Owner-supplied boundary files are now present and validated: 146 district GeoJSON features, 2,190 sub-county GeoJSON features, and a 146-feature Esri JSON district alternative. They remain unimported until the approved national hierarchy and effective date are supplied; see `docs/architecture/GEOJSON_BOUNDARIES.md`.
- Screenshot labels, values, and names are illustrative mock-up material, not production configuration.
- The exact production DHIS2 URL must be verified; do not silently substitute a hostname. Owner-supplied host text is approximately `HMIS.hhs.go.ug` via `DHIS2_BASE_URL`.
- Phase 2 synthetic fixtures and mocked connector tests do **not** close any row in this register.
- Live DHIS2 verification status: connector implementation complete; live DHIS2 verification pending authorised endpoint configuration and credentials.
- EPI performance bands and dropout thresholds remain TBD. Do not use screenshot targets as production rules.
- Confirmed MPDSR semantic date/linkage fields, retention, and sensitive-data policy remain owner decisions.

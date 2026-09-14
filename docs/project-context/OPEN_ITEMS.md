# Open Production Inputs

Do not invent any item in this register. Each requires a project-owner, Ministry/programme, or authorised technical decision before production configuration.

| Area | Required input | Why it is needed |
|---|---|---|
| DHIS2 connectivity | Authentication method and credentials for the known host `https://hmis.health.go.ug` (D-049), network access from Render, and authorisation for a first bounded, owner-supervised validation | Host and refresh cadence are decided (D-047, D-049). `DHIS2_ENABLED`/`SYNC_ENABLED` default false; discovery and refresh commands are prepared and inert. |
| DHIS2 metadata | Org-unit UIDs, aggregate data-element/indicator and category mappings, MPDSR program/stage/field semantic mappings, metadata access validation | Correct extraction and calculation |
| Geography | Approved analytical hierarchy, current/historical org-unit mappings, city/sub-county treatment, boundary effective date, and owner approval of the supplied boundary files | Complete, unambiguous geometry import and map drill-down |
| Population | Approved population files, source/version/validity rules, all required years, official facility catchment values, and facility override approval workflow | Population denominators and reproducibility |
| EPI governance | Authoritative indicator bands/targets not yet specified, plus relevant timeliness/continuum definitions | RAG classification without invention |
| Indicator governance | Any additional MNCH definitions, mapping exceptions, direct-percent contracts, valid-from/to dates, and approved methodology owners | Registry completion |
| MPDSR data contract | Exact date fields for death, notification, and review; event linkage/shared identifier; cause taxonomy; sensitive-data access and retention policy | Correct cohorts, timeliness, privacy |
| Users/security | Named initial administrator and first user grants (geography, programme, action); future SSO/MFA provider | Local accounts for UAT (D-044) and retention durations (D-043) are decided. `scripts/create_initial_admin.py` provisions the first administrator without defaults; no real user was created. |
| Publishing | Approved official MoH logo asset; Excel, national/regional/district/facility/MPDSR PowerPoint and report templates; export retention | Professional governed outputs |
| AI | Approved provider/model(s), data-processing approval, cost/token limits, redaction policy, evidence schema, no-AI fallback | Safe bounded AI |
| Operations | Render account and Neon project (URLs, region, plan), monitoring and alert channels, backup cadence and restore test, SLAs | Hosting is decided (D-042) and `render.yaml` is prepared, but nothing was deployed and no Neon database was connected. |
| Local PostgreSQL credentials | Confirm the intended database/user name for the owner-supplied internal PostgreSQL password and whether the existing port-5432 instance is a disposable development target | The 2026-09-12 migration gate used a newly created isolated PostgreSQL 18.1 cluster with trust authentication on port 55432. The existing localhost:5432/5433 instances were not mutated and no password was written to the repository. |
| Playwright Chromium binary (workstation only) | Playwright-managed Chromium revision 1243 for `@playwright/test` 1.63 on this workstation | Only revision 1228 is cached locally. Local runs use the installed Chrome through `HPIP_BROWSER_EXECUTABLE`; CI installs managed Chromium with `npx playwright install --with-deps chromium`. |
| Phase 5–7 inputs | Approved AI provider/model and processing agreement; official MoH publishing templates; production hosting, Redis, monitoring, and PostgreSQL backup | Platform fallbacks exist. These inputs are still required before a production go-live. |
| Corrective snapshot operations | Redis-backed export/AI workers in the owner-approved topology, production query SLA, and map tile hosting if a basemap is required | Exact-run snapshot IDs are required. MapLibre renders owner geometry without a third-party basemap. Test/dev export generation may still be eager. |

## Open inputs raised by the 2026-09-13 material amendment

Implemented defaults below are fail-closed. None is an owner decision until accepted.

| Area | Required input | Current implemented behaviour |
|---|---|---|
| Base corrective prompt | The amendment supplements a corrective prompt that was not received in this session | Only the 17 amendment sections were implemented. Defects that exist only in the unreceived prompt are not addressed. |
| Sub-annual population year (§4) | **Resolved by D-045 (2026-09-14).** | FY rules for FY2024/25–FY2029/30 now cover `fy`, `fy_quarter`, `quarter`, `half` and `month`. Periods beyond the approved 2024–2030 source still return `population_rule_missing`. |
| Calendar-year population rule | **Resolved by D-045 (2026-09-14).** | Calendar years 2024–2030 are seeded with population year N. |
| Population workbook (§2/§3) | Approved national organisation-unit hierarchy; recorded alias decisions; owner approval of the imported draft versions. The source itself is approved (D-046). | Workbook verified unchanged: SHA-256 `5AE43DCA4533347FBB95C3F9B4E08A25C953C90905445614BA7D4E4BD3E75072`, 146 units (135 districts, 11 cities), 2024–2030, 1,022 cells, NATIONAL TOTAL equals the unit sum, Acholi N.5 totals 2,044,355 / 2,152,700 reproduced. Dry run against the synthetic seed: 3 exact matches (Pader, Kitgum, Soroti), 143 production-unresolved. All 146 rows can now be staged in `population_import_batches` without creating denominators. Reports: `docs/reconciliation/POPULATION_RECONCILIATION.{md,json}`. **No production import was performed; the staging run used a disposable scratch database.** |
| Population aliases | Decisions for `Kampala Capital City` ↔ the hierarchy's Kampala unit, `Gulu` ↔ Gulu District, and `Manafwa` ↔ Manafa if the hierarchy uses that spelling | Exact normalised name + unit type only. No fuzzy matching. An alias needs a proposal and a decision by a different `approve_population` user (system administrators excepted), both audited. |
| MPDSR sync window (§6) | Whether the Tracker `occurredAt` date is the death date or the report date; the approved follow-up window for completion counts | A zero is verified only by a successful, complete, non-truncated, current Tracker job whose window starts on or before the cohort start and ends on or after the follow-up end (notification +1 day, review +7 days) or the extraction date for counts. Operators pass `event_window_end` (Tracker jobs only, between the period end and today). Staleness uses `DHIS2_STALE_HOURS` (72). |
| MPDSR cause disclosure (§10) | Approved minimum cell count and disclosure levels | `MPDSR_CAUSE_MIN_CELL_COUNT` is unset, so cause patterns are withheld everywhere. When set, disclosure is limited to country/region/sub-region, requires MPDSR programme scope plus `view_mpdsr_events`, counts structured categories only, and suppresses categories below the minimum or reported by a single unit. |
| Region/sub-region boundaries (§13) | Approved region or sub-region geometry, if national maps are required | National maps report `geometry_unavailable_for_level`. District polygons are never substituted for regions. |
| Ranking defaults (§9) | Owner confirmation of the platform defaults | Five best and five worst units; ties broken by name; PMR, fresh stillbirth rate, MMR and all MPDSR indicators are never ranked; unclassified (TBD) indicators are never ranked. |
| AI evidence size | Confirmation of the 20,000-character provider limit | An oversized package no longer blocks the user: the external provider is skipped (`evidence_exceeds_provider_limit`) and the local deterministic answer is returned. Evidence rows omit unrecorded fields and repeated quality flags are grouped with an occurrence count. |
| Frontend build output owned by another account | Owner removal of `.build-quarantine/` (elevated: `takeown /F <path> /R /D Y`, `icacls <path> /grant "%USERNAME%:(OI)(CI)F" /T /C`, `Remove-Item -LiteralPath <path> -Recurse -Force`), and stopping any other agent account (`CodexSandboxOffline`) from building in this checkout | `distDir` is back to the standard `.next`. Build folders written by `CodexSandboxOffline` were moved (not deleted) into `.build-quarantine/20260913-frontend` and `.build-quarantine/20260914-frontend`. The second relocation was needed because that account rebuilt into `.next` during this session. A `prebuild` guard (`frontend/scripts/prepare-build-dir.mjs`) now fails fast with the locked paths and the owner command instead of letting Next.js 15.5.25 retry `EPERM` forever. |
| Playwright in the project directory | None, provided no other account rebuilds into `.next` | Playwright runs against the real repository through the same-origin proxy; see CHANGELOG_CONTEXT for the latest counts. |
| Formula versions without dated history | Whether undated legacy catalogue versions may be used in staging/production (`FORMULA_UNDATED_FALLBACK=true`), or effective dates for each approved formula version | Dated history is authoritative; a period with no in-force dated version is `formula_version_unavailable`. Undated versions are used only in development/test by default. **Production leaves every seeded (undated) indicator unavailable until this is decided.** |
| MPDSR timeliness semantics | Which DHIS2 event dates are the death, notification and review dates | Timeliness only calculates from mapped `death_date`/`notification_date`/`review_date`; no production mapping exists, so production timeliness has no data and stays unverified. Date-field mappings were not invented. |
| Boundary effective date and duplicates | Owner-verified boundary effective date; decision on `UGANDA_SUBCOUNTIES.json` OBJECTID 1240, shared by NYAMIRAMA (Kanungu) and KYANGWALI (Kikuube) with different geometry but identical stated area and perimeter; policy for 44 repeated sub-county names | Geometry activation refuses without `effective_date_verified`. See `docs/reconciliation/GEOJSON_RECONCILIATION.md`. |
| Health sub-region membership | Approved district/city to health sub-region membership | Sub-region population totals are reported as not calculated. Workbook broad regions are never used as analytical parents. |
| Redis on the workstation | A disposable Redis for local real-Redis tests (optional) | Real Redis and Celery-over-Redis tests run in CI only; locally they skip with a stated reason. Docker is not installed on this workstation, so compose and container smoke tests were not executed locally. |

## GeoJSON facts to preserve

- `UGANDA_DISTRICT.json`: 146 valid district features.
- `UGANDA_SUBCOUNTIES.json`: 2,190 valid sub-county features.
- `UGANDA_DISTRICTS.json`: alternate Esri JSON.
- Synthetic seed dry run: district 3/146 name-matched; sub-county 0/2,190 matched. Expected because the approved national hierarchy is absent. Do not apply fuzzy guesses.

## Clarifications to preserve

- No production performance values, MoH UIDs, or credentials are present in this workspace. The owner-supplied district/city population workbook is present as a candidate source (see the amendment table above); it has not been imported or approved, and it never supplies facility or sub-county populations.
- Owner-supplied boundary files are now present and validated: 146 district GeoJSON features, 2,190 sub-county GeoJSON features, and a 146-feature Esri JSON district alternative. They remain unimported until the approved national hierarchy and effective date are supplied; see `docs/architecture/GEOJSON_BOUNDARIES.md`.
- Screenshot labels, values, and names are illustrative mock-up material, not production configuration.
- The DHIS2 base host is `https://hmis.health.go.ug` (D-049). Authenticated access, metadata and live synchronisation have not been verified and must not be claimed.
- Phase 2 synthetic fixtures and mocked connector tests do **not** close any row in this register.
- Live DHIS2 verification status: connector implementation complete; live DHIS2 verification pending authorised endpoint configuration and credentials.
- EPI performance bands and dropout thresholds remain TBD. Do not use screenshot targets as production rules.
- Confirmed MPDSR semantic date/linkage fields, retention, and sensitive-data policy remain owner decisions.

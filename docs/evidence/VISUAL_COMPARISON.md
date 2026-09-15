# Visual comparison matrix — reference screens versus implementation

The reference PNGs at the repository root and `index(1).html` specify layout, density, colour relationships and interaction posture only. Their numbers are illustrative and were not copied. Every value in the application comes from a server-calculated, committed snapshot; with the synthetic development fixtures most values are legitimately "No data".

Screenshots: `docs/evidence/screenshots/` (refreshed only with `npm run e2e:evidence`; snapshot identifiers and extraction timestamps are masked). Structural gates: `frontend/e2e/visual-acceptance.spec.ts`.

"Owner input" means the difference cannot be closed in code without an owner-supplied asset, rule or data source.

## Shared shell (all screens)

| Reference component | Implemented component | Remaining intentional difference | Reason | Owner input |
|---|---|---|---|---|
| Ministry crest and wordmark in the sidebar | `AppShell` brand: dashed "Crest" slot labelled "Reserved for the approved Ministry of Health crest", "Ministry of Health / Republic of Uganda" | No crest image | No approved asset has been supplied; a crest is never extracted from a mock-up | Yes — approved crest asset |
| Navy sidebar with outline icons and a filled active item | Local SVG outline icons (`Icon.tsx`) on every navigation item; gradient active pill with white icon and label; two labelled groups (geography screens, programme workspaces) | Nine workspace entries instead of the reference's eight generic items | The owner requires the ten specialised workspaces (administration shown only with `manage_users`) | No |
| "Healthier People…" slogan and flag stripe in the sidebar footer | Authorised-programme note and product name with a neutral blue accent | No slogan, no flag colours | An official slogan or national colours would imitate branding that has not been supplied | Yes — approved tagline/brand treatment |
| Topbar: title, subtitle, notification bell, profile, tagline | `topbar`: 28px title, screen · scope subtitle, bell linked to the Data quality workspace with the snapshot's open-flag count, avatar, name and role, sign out, platform note | Tagline reads "Deterministic, permission-scoped analytics from committed snapshots" | The reference tagline is a mock-up slogan; the notification is a real data-quality link, not a decorative bell | Optional — approved tagline |
| Filter row: scope, role, period, compare, geography, search | `FilterStrip`: scope and role chips with icons; Period, Compare, Geography, Programme, Indicator selects with field icons; Apply; `SearchBox` | Two extra selects (programme, indicator) and an explicit Apply button | Analytical execution is a CSRF-protected POST per request; module and indicator are part of the snapshot request | No |
| Search box | Combobox over `GET /search`: authorised organisation units (geography-path scoped) and indicators in authorised programmes; keyboard navigation | Does not search events, users or free text | Server-side scope; MPDSR events are never searchable | No |
| Pale natural background | Faint blue botanical linework (≈7% opacity) at the top-right of the canvas plus radial gradients | Linework is abstract, not photographic | Contract: natural treatment must never compete with data | No |
| Six KPI cards: label, value, delta arrow, "vs" period, status dot, sparkline | `KpiCard`: label, value, arrow (direction from the server's change value, colour from the server's interpretation), "vs" comparison period, status pill with dot, sparkline of server trend values | Cards show "No data" with the reason instead of numbers for synthetic data | Missing stays unavailable, never zero | Data — DHIS2 and approved populations |
| Downloads: Excel, PowerPoint, report with source/freshness footer | `DownloadsBar`: format icons, labels and hints, server availability, snapshot and freshness metadata | PDF/Word shown disabled; "platform-default templates" note | Official templates are pending; unavailable generators are never faked | Yes — official templates |

## National overview (`ChatGPT Image … (1).png`)

| Reference component | Implemented component | Remaining intentional difference | Reason | Owner input |
|---|---|---|---|---|
| Regional performance map with legend and zoom | `MapPanel` → `AdaptiveMap` (MapLibre, snapshot cohort only) | Shows "Boundaries unavailable for this level" inside the panel | No approved region geometry; district shapes are never substituted | Yes — approved region boundaries, hierarchy and effective date |
| AI performance insights with icons and "Generate brief" | `InsightsPanel` (four prioritised deterministic insights, severity icons, "View all") plus `AskTheData` with "Generate brief" | Insights and Ask the Data are separate panels | Deterministic findings are always shown; AI requests are explicit | No |
| Regional scorecard with RAG cells | `ScorecardPanel` unit matrix (child units × headline indicators, RAG/BLUE cell fills) with an Indicators tab | Cells read "No data" | No calculated values in the synthetic snapshot | Data |
| Monthly trends (multi-series) | `TrendPanel` (single selected indicator, gaps for missing periods) | One series at a time | Keeps per-indicator units and scales honest | No |
| Downloads footer | `DownloadsBar` | See shared shell | — | Templates |

## Regional overview (`… (2).png`)

| Reference component | Implemented component | Remaining intentional difference | Reason | Owner input |
|---|---|---|---|---|
| District map | `MapPanel` | Unavailable state | No approved district boundary activation | Yes — boundary approval references |
| Priority insights | `InsightsPanel` | — | — | No |
| District performance scorecard | `ScorecardPanel` (districts) | — | — | Data |
| Top priority districts table with key issue and recommended action | `RankingPanel` (best / needs attention from the server's approved ordering rule) | No free-text "recommended action" column | Recommendations would be invented; only server rankings and reasons are shown | Yes — an approved recommendation source, if wanted |

## District facility performance (`… 10_55_11 PM.png`)

| Reference component | Implemented component | Remaining intentional difference | Reason | Owner input |
|---|---|---|---|---|
| Facility performance table with level and overall status | `ScorecardPanel` facility matrix (facility, level, headline indicators) | No "Overall" composite column | Composite scores are prohibited by the UI contract | No |
| Key insights | `InsightsPanel` | — | — | No |
| Facility trends | `TrendPanel` | Single indicator | As above | No |
| Top/bottom facilities with indicator tabs | `RankingPanel` for the selected indicator | Indicator chosen in the filter strip rather than panel tabs | One snapshot, one selected indicator | No |

## Facility profile (`… (3).png`)

| Reference component | Implemented component | Remaining intentional difference | Reason | Owner input |
|---|---|---|---|---|
| Facility identity and catchment-population alert | `FacilityIdentity` strip, `StatusLine` population notice, `CatchmentPanel` draft workflow | — | — | Data — approved catchment populations |
| KPI strip, trends, indicator scorecard | `KpiStrip`, `TrendPanel`, `ScorecardPanel` (indicators) | — | — | Data |
| Data-quality alerts | `QualityFlagsPanel` (compact, paginated) | — | — | No |
| AI summary and recommendations | `AskTheData` | No generated recommendations shown until requested | AI output is explicit and evidence-bound | Approved AI provider (optional; deterministic fallback exists) |

## MPDSR (`… (4).png`)

| Reference component | Implemented component | Remaining intentional difference | Reason | Owner input |
|---|---|---|---|---|
| Perinatal and maternal notification/review scorecard | `ScorecardPanel` (indicators) "Notification and review scorecard" | Single indicator table rather than grouped perinatal/maternal column headers | Server returns indicator rows; grouping would need a governed presentation mapping | No |
| Cause patterns with Perinatal/Maternal tabs and bars | `MpdsrCausePanel` with "Cause patterns" / "Active reviews" tabs | Causes withheld | No approved cause taxonomy or minimum cell count; free text is never stored | Yes — cause taxonomy and disclosure rule |
| Quarterly process chart | `TrendPanel` "MPDSR process trends" | Line of the selected indicator | Timeliness semantics are not yet approved | Yes — MPDSR date semantics |
| Data-quality issues | `QualityFlagsPanel` (compact) | — | — | No |
| Key learning | `InsightsPanel` titled "Key learning" (deterministic) | No narrative learning text | Narratives are not invented | No |

# UI Visual Contract

## Interpretation and baseline

The supplied images are approved design references. **Their numerical values are not production data unless separately validated.** They are desktop reference canvases at **1672 × 941 px**. Preserve the shared information density, layout, colour relationships, dashboard rhythm, and interaction posture; do not treat them as loose inspiration.

| Screen | Source image | Major components | Hierarchy and interaction assumptions | Notable styling / tokens needed |
|---|---|---|---|---|
| National overview | `ChatGPT Image Sep 11, 2026, 10_54_55 PM (1).png` | National KPI strip; region map; AI insights; regional RAG scorecard; monthly trends; downloads | Map and scorecard drill to authorised regional scope; selector state drives all panels; evidence opens from measures | map RAG legend; compact KPI cards; three-column analytic middle row |
| Regional overview | `…10_54_55 PM (2).png` | Regional KPI strip; district map; priority insights; district scorecard; monthly trends; priority-district table | District map/table drill to authorised district; prioritisation is evidence-based | same shell; large map; dense bottom priority table |
| Facility profile | `…10_54_55 PM (3).png` | Facility identity/context strip; catchment-population alert/editor; KPIs; trends; scorecard; quality alerts; AI/action panel; exports | Population edit is permission-controlled; only population-derived indicators degrade if missing | contextual strip; inline blue info banner; alert severities; footer downloads |
| MPDSR | `…10_54_55 PM (4).png` | Perinatal + maternal process scorecard; cause tabs; quarterly process chart; data-quality list; key-learning panel | Status and evidence drill-down; maternal data obeys stricter privacy; ACTIVE distinct from completed | grouped table headers; neutral counts; RAG/BLUE only performance cells; controlled cause tabs |
| District facility performance | `ChatGPT Image Sep 11, 2026, 10_55_11 PM.png` | District KPI strip; full facility scorecard; key insights; facility trends; top/bottom ranker; exports | Mandatory district-to-facility comparison; indicator selector/ranking and authorised facility drill-down | dense facility table; overall status pill; tabbed ranker |

## Common layout anatomy

- Fixed left navigation about 236 px wide, dark navy (`#06345a`-like) with white outline icons; active item is cyan/blue with a rounded rectangle. Ministry layout marks are reference-only until an approved asset is supplied.
- Main canvas uses a pale, nearly white blue background. Top header is roughly 80 px, with product title/subtitle left and notification/profile/tagline right. A compact filter row follows: scope/role, period, comparison, geography, and search.
- KPI row uses six equal compact white cards, thin pale-blue border, approximately 10–12 px radii, modest/no heavy shadow. Anatomy: label, large navy number, delta with directional colour, status pill, short blue sparkline.
- Content cards are crisp white, 10–12 px radius, pale blue-grey outlines, 12–16 px internal padding, and 12–14 px gutters. Tables use pale-blue headers, fine grid lines, 35–42 px rows, bold row labels/aggregate rows, and readable RAG fills.
- Charts use fine pale grids, bright blue/green/yellow/red series, 2–3 px lines, small circular points, concise legends, and compact titles/actions. Maps use discrete green/yellow/red/blue (water/no-data) legend states.
- Footer download surface uses Excel green, PowerPoint orange/red, and report blue accents; show source/freshness metadata.

## Token plan for implementation

| Token family | Direction |
|---|---|
| Typography | Clean humanist sans, likely Inter/Arial-like; navy high-weight headings; 28–32 px product title; 18–20 px section titles; 12–14 px metadata/table text; tabular numerals. |
| Navigation | Navy-to-deep-blue vertical treatment; active cyan-blue; white iconography; subdued separators. |
| Surfaces | `#f5fbff`-like page field, white cards, pale-blue (`#d7e8f5`-like) borders/headers, very light/soft shadow only. |
| Semantic status | green, amber/yellow, coral red, and clear blue for quality/non-assessable; status must include text/icon, not colour alone. |
| Spacing/radius | 8 px base rhythm; 10–12 px card radius; compact analytical density rather than roomy marketing layout. |
| Icons | Simple outlined, consistent stroke icons for nav, headings, filters, alerts, and actions. |

## Background and prohibited drift

Keep the blue/navy DHIS2-like analytical shell. A very pale blue gradient with very-low-opacity organic/botanical linework may sit behind content. It must be felt as polish, not read as a prominent “nature background.” Do not replace the blue identity with green, use heavy glassmorphism/shadows, enlarge cards into a sparse marketing dashboard, use generic gradients, crop/distort official branding, or convert dense scorecards into decorative widgets.

Responsive implementation must preserve hierarchy: desktop tables can scroll horizontally or become deliberate card/summary views at smaller breakpoints, without losing RAG status, evidence access, or filter scope.

Phase 4 implements this contract in `frontend/src/app/globals.css` and the reusable dashboard components. Screenshot numbers remain illustrative and are not production values.

## HTML prototype (`index(1).html`) — layout reference only

The owner-supplied HTML prototype may guide layout, density and interaction patterns. Its content is not a specification. The following are **prohibited** in the application unless separately validated against the canonical handoff and approved configuration:

- Invented EPI performance bands (for example ≥90% / ≥75%) or any EPI RAG thresholds; EPI bands remain TBD.
- Under-five mortality, "full immunization" or other indicators absent from the approved catalogue.
- Composite or overall performance scores and league-table scores.
- Facility populations estimated from district populations.
- Whole-number MPDSR precision or MPDSR percentages rounded differently from the catalogue.
- Demonstration values, targets, provider names, labels, org-unit mappings and embedded assumptions.
- Client-side health calculations of any kind; the browser renders server-calculated snapshot values only.
- A production dependency on Google Fonts; fonts may be hosted locally only from an approved asset.

The Next.js application remains the implementation target.

## Implementation status (2026-09-14)

- `frontend/src/app/globals.css` carries the prototype's visual tokens only: navy scale `#061a31`–`#1a4a74`, blue scale `#12509e`–`#edf4fd`, RAG backgrounds, canvas `#f2f7fc`, 10px radius, 14px gap, 30px control and row height, 236px navy-gradient sidebar, subtle radial canvas background, sticky table headers, 430px evidence drawer, Excel/PowerPoint/report button colours. System fonts only.
- Responsive: KPI strip 6 → 3 columns at 1320px → 2 at 760px; labelled 196px sidebar at tablet width (no icon-only collapse without icons); stacked navigation on phones; `prefers-reduced-motion` honoured; visible focus rings; `aria-current` on active navigation.
- Workspaces are compositions of the same typed snapshot (`frontend/src/lib/workspaces.ts`): ANC and MNCH, intrapartum and newborn, immunisation (with continuum), MPDSR (process extras, counts unclassified), maps, trends, data quality (console of flags and unavailable reasons), reports and exports (job history with retry and expiry), AI insights, administration (registry status; refused for non-administrators).
- Unavailable values show the server's reason in words (for example "Population denominator unavailable") and never zero.
- Contract tests (`frontend/src/test/prototype-contract.test.ts`, `backend/tests/test_prototype_contract.py`) block prototype values, client-side calculations, invented EPI bands, hosted fonts and prefilled accounts.
- Screenshots from the latest Playwright run are written to `frontend/e2e-screenshots/` (not tracked in Git).

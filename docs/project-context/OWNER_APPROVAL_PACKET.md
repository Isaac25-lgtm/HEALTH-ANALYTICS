# Owner approval packet — live DHIS2 data plane

Generated 2026-09-20 against the live national instance `https://hmis.health.go.ug` (DHIS2
**2.41.8.1**) using the configured read-only credential. Every figure here was measured, not
assumed. Nothing in this packet has been applied: each row below is a decision only the project
owner, Ministry, or a named clinical authority can make.

Supporting artifacts live in the gitignored `.local/dhis2/` directory and are regenerable:
`org-units-l1-l3.json`, `metadata-full.json`, `source-mapping-proposal.json`.

## What was established without needing a decision

| Fact | Value | How it was established |
|---|---|---|
| DHIS2 version | 2.41.8.1, ISO8601 calendar | `/api/system/info` |
| Analytics tables last built | 2026-09-20 01:45, ~16 h before the check | `/api/system/info` |
| Connector account identity | `biostat.pader` / `ALoyniVOIY2`, 138 authorities, no `ALL` | `/api/me` |
| Account **data-view** scope | **National** — `MOH - Uganda`, UID `akV6429SUqu`, code `UG256` | `/api/me` `dataViewOrganisationUnits` |
| Account **capture** scope | Pader District only (level 3) | `/api/me` `organisationUnits` |
| National hierarchy reach | 1 / 15 / 146 / 178 / 2 206 / 8 787 / 96 by level | `withinUserDataViewHierarchy=true` |
| Period identifiers | Monthly `yyyyMM`, Quarterly `yyyyQn`, SixMonthly `yyyySn`, Yearly `yyyy`, **FinancialJuly `yyyyJuly`** | `/api/periodTypes` |

The account can read national aggregate data even though it can only capture in Pader, because
analytics reads are governed by the data-view scope. Extraction is therefore technically possible
with this credential; whether it *should* be is decision **D-A** below.

### National data access is proven, not inferred

Metadata visibility is not data access, so a bounded read-only analytics request was made against
one non-sensitive aggregate element (`105-CL01` BCG doses, UID `MxAg9De4cra`) for one closed month
(June 2025). Nothing was written and nothing was stored.

| Check | Result |
|---|---|
| National root `akV6429SUqu` | 158,721 |
| District rows returned for `LEVEL-3` | **146 of 146, every one reporting** |
| Sum of the 146 district rows | **158,721 — reconciles exactly to the national figure** |
| Largest contributors | Wakiso 5.97 %, Kampala 5.41 % |
| Pader District | 600, **0.38 % of national** |

The national value demonstrably aggregates all 146 districts and cannot be a Pader-only figure.
The platform's analytical scope is therefore countrywide, and `biostat.pader` is an administrator
identity, not a scope limit. Ordinary users may later be restricted to a district, sub-county,
facility or programme; that restriction is enforced server-side and must never narrow the data
plane itself.

## Decisions required

### D-A. Integration credential

A personal district officer's account is currently the only configured credential. It has national
data-view reach, so it would work, but it ties national extraction to one person's account and to a
password that has already been disclosed in conversation.

| Option | Consequence |
|---|---|
| A1. Request a dedicated read-only national integration account | Preferred. Survives staff changes; scope is auditable; no personal password in server configuration; can be granted the 53 category option combinations this account cannot see (D-H). |
| A2. Continue with `biostat.pader` for UAT only, rotate immediately | Workable — national data access is proven above — but it ties countrywide extraction to one person's account. Must not reach hosted production. |

The current credential must be rotated regardless of the option chosen. Note that national access
is **not** the blocker it was feared to be: the remaining blockers are the approvals below.

### D-B. DHIS2 level → HPIP level mapping

The national hierarchy has **seven** levels; HPIP models **five**. The mismatch is not cosmetic and
cannot be guessed.

| DHIS2 level | Name | Live count | HPIP level | Status |
|---|---|---|---|---|
| 1 | National | 1 | `country` | Proposed, unambiguous |
| 2 | Region | 15 | `region` | Proposed, unambiguous |
| 3 | District/City | 146 | `district` | Proposed — matches the population workbook and the district boundary file exactly |
| 4 | DLG/Municipality/City Council | 178 | **no equivalent** | **Decision required** |
| 5 | Sub County/Town Council/Division | 2 206 | `sub_county` | Proposed |
| 6 | Health Facility | 8 787 | `facility` | Proposed |
| 7 | Ward/Department | 96 | below facility | Proposed: out of analytical scope |

**The question:** level 4 sits between district and sub-county. Options: (B1) collapse it, treating
level-5 units as direct children of level-3 districts; (B2) model it as a new HPIP level; (B3)
exclude level-4 units and any sub-county whose only parent is a level-4 unit. B1 is the least
disruptive and matches how the population and boundary files are organised, but it changes
parentage for any sub-county whose real parent is a municipality.

### D-C. Name alias decisions

Three names differ between the owner's files and the live instance. These are the **only**
unresolved names; everything else matched deterministically.

| Owner file spelling | Live DHIS2 unit | Appears in |
|---|---|---|
| `Luweero` | `Luwero District` | population workbook **and** district boundary file |
| `Ssembabule` | `Sembabule District` | population workbook **and** district boundary file |
| `Kampala Capital City` | `Kampala District` | population workbook only |

`Manafwa` matched exactly; the previously feared `Manafwa/Manafa` mismatch does not exist.

### D-D. Population crosswalk

Regenerated against the live hierarchy, replacing the earlier report that was produced against
synthetic development data.

| Measure | Result |
|---|---|
| Workbook units | 146 (135 districts, 11 cities), checksum `5ae43dca…` verified |
| Exact matches to live level-3 units | **143 / 146** |
| Requiring an alias decision | 3 (see D-C) |
| Unaccounted on either side | **0** |
| National total equals the sum of 146 units | **Yes, for all seven years 2024–2030** |

Approving D-C resolves the crosswalk completely. Population may then be staged and applied as
**draft** versions; approving a version is a separate transition.

### D-E. District boundary activation

| Measure | Result |
|---|---|
| Features in `UGANDA_DISTRICT.json` | 146, checksum `5a6024f5…` verified |
| Exact matches to live level-3 units | **144 / 146** |
| Requiring an alias decision | 2 (`Luweero`, `Ssembabule` — same as D-C) |
| Live units with no feature | 0 once aliases are approved |

Activation additionally requires, and none of these exists yet:
a boundary **effective date**, an **effective-date approval reference**, a **hierarchy approval
reference**, and a **feature-to-unit mapping decision reference**.

### D-F. Sub-county boundary activation

| Measure | Result |
|---|---|
| Features in `UGANDA_SUBCOUNTIES.json` | 2 190, checksum `49c0d093…` verified |
| Live level-5 units | **2 206** |
| **Gap** | **16 live sub-counties have no boundary feature** |

The file also contains a duplicated `OBJECTID` 1240 across two features with different parent
districts, so `OBJECTID` alone is not a national key; a parent-qualified key is required.

**The question:** activate sub-county geometry with 16 units unmapped and rendered as missing, or
withhold sub-county geometry until a complete file is supplied? Nothing will be activated partially
without an explicit partial-activation approval.

### D-G. Source mappings for 48 internal keys

`scripts/dhis2_mapping_proposal.py` generates candidates from live metadata for all
**48** source keys required by the 60 indicators (16 MNCH, 30 EPI, 14 MPDSR). Nothing is approved.

| Measure | Result |
|---|---|
| Source keys required | 48 |
| Keys with at least one candidate | 46 |
| Keys with no candidate at all | 2 — `ROTAV1`, `ROTAV2` |

**Read the candidate ranking as a search aid, not as clinical advice.** Name similarity in this
instance is actively misleading, and the ranking reflects it:

- `MR` (measles-rubella **vaccination**) name-matches `033B-CD10a. Measles - Cases`, a disease
  surveillance count. Binding it would put outbreak counts into a coverage indicator.
- `MV1`–`MV4` are **Malaria Vaccine** doses per the approved catalogue, not measles.
- The correct-looking immunisation elements cluster in a `105-CL*` series (`105-CL01. BCG`,
  `105-CL10. DPT-HepB+Hib 1`), but the ranking does not reliably place them first.
- Several keys are **category option combinations of one element**, not elements of their own:
  `105-AN01a. ANC 1st Visit for women` carries the `MCH Age` category combination, which is where
  the ANC1 age bands live. `105-CL01. BCG` carries `EPI Age & Service Delivery Type`.

Every one of the 48 rows requires review by someone with authority over Uganda's HMIS definitions.
A partial mapping set cannot activate a programme: coverage is enforced per formula.

### D-H. Category-option-combination visibility

The connector account sees **3 135 of 3 188** category option combinations the server reports —
**53 are counted but not returned**, reproducibly, at two different page sizes. This is almost
certainly sharing/ACL filtering on the account.

If any approved mapping needs one of the 53 hidden combinations, extraction will silently miss
those category rows. Resolving this is part of D-A: a dedicated integration account should be
granted visibility of every category combination the indicators require.

### D-I. Formula effective dates

The database holds 60 indicator versions, all marked current, **all undated**. Production refuses
undated formula versions, so on a production deployment every indicator would become unavailable.

| Option | Consequence |
|---|---|
| I1. Supply approved effective dates for all 60 | Correct long-term answer; requires a methodology owner. |
| I2. Explicitly approve `FORMULA_UNDATED_FALLBACK` for UAT only | Unblocks UAT; must not persist into production. |

This flag has not been enabled. Enabling it silently was explicitly out of scope.

### D-J. MPDSR

Remains deliberately blocked, and no MPDSR line list was retrieved. Still required before any
extraction: the death/notification/review date fields, the event linkage identifier, an approved
cause taxonomy with a minimum disclosure cell count, and the programme/stage/field mapping.

## Sequence once approvals exist

1. D-A, D-B → import the hierarchy and organisation-unit mappings (transactional, dry-run first).
2. D-C → stage the population workbook, regenerate reconciliation, apply the crosswalk as drafts.
3. D-D → approve population versions through the governed transition.
4. D-C, D-E (+ effective date and references) → activate district geometry.
5. D-F → decide sub-county geometry.
6. D-G, D-H → approve source mappings, then run one supervised bounded extraction before any
   national refresh.
7. D-I → decide formula dating before any production deployment.

## What is deliberately still true

- No DHIS2 write of any kind has been made, and none is possible through this codebase.
- No synthetic observation exists in the live database: 0 raw aggregate values, 0 source mappings,
  0 organisation-unit mappings, 0 sync jobs.
- Scheduled refresh remains blocked by its own preflight until approved mappings exist.
- EPI performance bands, the MoH crest, publishing templates and AI provider approval remain
  outstanding and are unaffected by this packet.

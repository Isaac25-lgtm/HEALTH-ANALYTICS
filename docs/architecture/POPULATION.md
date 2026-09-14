# Population resolution methodology

Population is a versioned registry. Financial-year mapping is configuration, not indicator code.

## Year resolution

`period_population_rules` stores the current binding convention:

| Financial year | Population year | Applies to |
|---|---|---|
| FY2024/25 | 2024 | full financial year (`fy`) |
| FY2025/26 | 2025 | full financial year (`fy`) |

Each rule records `scope_kind` (`financial_year` or `calendar_year`), `applies_to_period_kinds`, `approval_status`, and an optional programme. Resolution (amendment §4):

1. Only approved rules are used.
2. A programme-specific rule is preferred; another programme's rule is never used.
3. The period kind must be listed in `applies_to_period_kinds`.
4. Conflicting approved rules, or no rule, return `population_rule_missing`. No year is inferred.

No explicit rule for months, quarters or half-years was found in the handoff or the owner's workbook guide, which states only calendar-year and financial-year rules. Sub-annual population-derived values therefore stay unavailable until an approved rule names those period kinds (for example `applies_to_period_kinds=["fy","fy_quarter"]`). Migration 0007 kept the existing FY rules as FY-only. See `OPEN_ITEMS.md`.

Selection of a national/subnational version is deterministic:

1. Approved.
2. Valid for the requested date (`valid_from` / `valid_to`).
3. Actually covers the requested year and geography.
4. Competing approved versions: latest `valid_from`, then latest `created_at`, then version code.
5. Selection reason is recorded. The globally newest approved version is not used merely because it was created last.

## Period adjustment

Applied **only** to population-derived target denominators:

`period target = annual population × coefficient × months_in_period / 12`

| Period | Fraction |
|---|---|
| Financial or calendar year | 12/12 |
| Quarter | 3/12 |
| Month | 1/12 |
| Six-month period | 6/12 |

Not applied to ANC1, deliveries, live births, birth-asphyxia cases, reported deaths, event counts, or other service-derived denominators.

## Parent aggregation policy

Default policy: `direct_or_complete_children`.

1. Use an approved population recorded directly on the requested unit.
2. Otherwise sum the nearest complete cohort of one aggregation class from the **same approved version**. Districts and cities are one class (`district_equivalent`); nested units of one class are counted once.
3. Never mix a parent value with descendant values, and never mix classes.
4. Facility catchment entries are never summed into a parent, and facility-class values are skipped.
5. Incomplete children return `unavailable`, not zero. The resolution records `aggregation_level` and `child_unit_ids`.

## Facility catchment

- Creating a draft does **not** supersede the current approved value.
- The approved value remains active until a replacement is approved.
- Approval is atomic: approve the replacement, supersede the prior approved entry, record approver/timestamp/reason and before/after values, preserve history. The prior row is flushed before the new current-approved flag is set so the partial unique index holds.
- Rejection leaves the existing approved population active.
- `POST /populations/facility` requires `edit_population`.
- Approve/reject require `approve_population`. The entering user cannot self-approve unless they are a system administrator.
- Approval uses `SELECT … FOR UPDATE` on the current approved row (effective on PostgreSQL).
- Population must be finite and greater than zero; year must be inside `POPULATION_YEAR_MIN`–`POPULATION_YEAR_MAX`; source name and reason have bounded lengths. Invalid requests return 422.

Missing facility population does not block facility analysis. Population-derived indicators return a typed unavailable/BLUE result. Service-derived indicators continue.

When a facility entry supplies the denominator, `facility_population_entry_id` is stored. That row is not attributed to an unrelated national population version. Methodology responses expose source, year, approval state, and official/estimated classification.

## APIs

- `GET /populations?org_unit_id=&year=`
- `GET /populations/resolve?org_unit_id=&period=`
- `GET /populations/versions`
- `POST /populations/import` creates a governed draft from organisation-unit codes and year/value rows
- `POST /populations/versions/{version_id}/approve`
- `POST /populations/versions/{version_id}/reject`
- `POST /populations/facility`
- `POST /populations/facility/{entry_id}/approve`
- `POST /populations/facility/{entry_id}/reject`

No official national or facility population values are seeded.

## District/city population workbook (amendment §2/§3)

`backend/app/services/population_workbook.py` and `backend/scripts/import_population_workbook.py` govern the owner-supplied `Uganda_District_City_Populations_2024_2030.xlsx`.

- **Identity.** The file is opened read-only after its SHA-256 matches `5AE43DCA4533347FBB95C3F9B4E08A25C953C90905445614BA7D4E4BD3E75072`, and re-checked after reading. A different checksum is a new source (`checksum_mismatch`).
- **Structure checks.** Exact header row; District/City types only; positive whole numbers; no duplicate normalised names; NATIONAL TOTAL present and equal to the unit sum for every year. Verified facts: 146 units (135 districts, 11 cities), years 2024–2030, 1,022 cells.
- **Reconciliation (dry run by default).** Each row is `matched_exact` (exact normalised name + type), `matched_alias` (approved alias to a district-equivalent unit), or blocking: `unmatched`, `ambiguous`, `type_mismatch`, `pending_alias`, `rejected_alias`, `invalid_alias`, `duplicate_target`. Internal district/city units without a source row are reported. There is no fuzzy matching.
- **Aliases.** `population_source_aliases` preserves the source name and the target name. `edit_population` proposes (with a note and geography access); a different `approve_population` user decides (system administrators excepted). Both steps are audited.
- **Apply.** Blocked unless reconciliation is clean, the importer holds `edit_population` for every matched unit, and the checksum was not already imported. Apply creates two **draft** versions — census 2024 and projections 2025–2030 — with source dataset, file name, checksum and sheet; each value keeps source name, type, Region (descriptive only) and column label. NATIONAL TOTAL is imported only with `--include-national-total --national-org-unit-code <country>` as a direct country value. Facilities and sub-counties never receive workbook values. Approval uses the existing version approval workflow.

```
python scripts/import_population_workbook.py                 # dry run
python scripts/import_population_workbook.py --report out.json
python scripts/import_population_workbook.py --apply --version-code <CODE> --username <importer>
```

No import has been performed; production application waits for the approved hierarchy and alias decisions.

Ordinary population listing returns approved version values only. Bulk import requires `edit_population`; approve/reject requires `approve_population`, locks the draft row, and prevents non-admin self-approval. A caller-supplied version cannot bypass approval, validity date, year, or geography coverage checks. The owner will supply the district population values later; none were inferred from the boundary files.

# Indicator registry and formula engine

The engine is configuration-driven. There is no `eval`, no executable SQL expressions, and no user-authored code.

Formulas live in `backend/app/domain/indicator_catalog.py` and are persisted as `indicator_versions.formula_spec` / `classification_spec`. Specs are validated with typed Pydantic models (`extra=forbid`) before persistence/execution. Unknown operations are rejected. Semantic source keys are used; DHIS2 UIDs never enter this module.

## Constrained formula kinds

| Kind | Behaviour |
|---|---|
| `ratio` | `SUM(numerators) / SUM(denominators) × multiplier` |
| `count` | Sum of source keys |
| `direct_percentage` | Use only a direct source percentage at the requested geography (KMC) |
| `dropout` | `(Dose1 − FinalDose) / Dose1 × 100` |

Denominator modes: `population`, `source_keys`, `event_count`.

Required composite components default to **all present**. If any required key is missing, the composite is unavailable, missing keys are listed, a quality flag is raised, and the absent component is not treated as zero. A reported zero remains a valid zero. Partial composites are not the default.

## Source aggregation

`resolve_source_key` does not sum the selected unit and every descendant.

1. Determine the analytical row level.
2. If an approved direct value exists for the selected geography and policy permits it, use only that value.
3. Otherwise select one consistent descendant level and use only that level.
4. Never combine parent and descendant rows.
5. Numerator and denominator use the same compatible scope.
6. Incomplete child coverage returns a quality/non-assessable state when policy requires completeness.
7. The selected policy, level, and source unit IDs are stored on the calculated value and run snapshot.

Example: parent `50/100` plus children `40/100` and `10/100` resolves to direct `50/100` under the registered direct-preferred policy—never `100/300`.

KMC has no approved raw numerator/denominator pair. Child KMC percentages are never summed or averaged. If the requested geography has no direct percentage, KMC is unavailable.

## Classification

Performance status is computed separately from quality status.

- Higher-is-better, lower-is-better, desired-range (C-section), teenage-pregnancy inverse, MMR bands, maternal coverage (green only at exactly 100%).
- Band edges use display-precision comparisons so values such as 4.94 and 4.95 do not fall into a gap between 4.9 and 5.0.
- EPI coverage remains `unclassified` until authoritative bands are supplied.
- Dropout, including MV1-to-MV4, remains unclassified. No EPI dropout thresholds were invented.
- Counts stay neutral (no RAG colour).
- BLUE is quality/non-assessable, not success.
- Values above 100% are never silently capped.

Over-100 behaviour is per indicator:

- Institutional delivery: retain performance (may be valid).
- KMC and successful resuscitation: BLUE.
- IFA: retain value and raise a quality flag.

Zero denominator returns N/A, not 0%. Missing source remains missing.

## Periods

Supported keys include FY2024/25, FY2025/26, FY quarters (Q1 = Jul–Sep, Q2 = Oct–Dec, Q3 = Jan–Mar, Q4 = Apr–Jun), months, and calendar years. The parsed period carries `parent_fy`. January–March inside FY2025/26 (`FY2025/26Q3`) uses the configured FY2025/26 population year **2025**, not 2026.

## Added Phase 2 contracts

In addition to the previously registered MNCH formulas:

- perinatal deaths notified / reviewed counts
- maternal deaths reported / notified / reviewed counts
- maternal timely notification (completed same/next-day notifications ÷ reported maternal deaths; maternal bands; BLUE when non-assessable)
- maternal timely review (completed reviews within 0–7 calendar days ÷ reported maternal deaths; same maternal bands)
- MV1-to-MV4 dropout (unclassified)

ACTIVE MPDSR events are not completed and are excluded from completed numerators.

## Calculation runs

`POST /calculations/run` requires a programme. It stores:

- software/release version;
- indicator IDs/versions and complete formula/classification specs;
- geography, programme, period;
- mapping IDs/versions actually used (not a hard-coded `v1` and not the formula version);
- population year, selected policy, population version **or** `facility_population_entry_id`;
- raw aggregate row IDs and checksums;
- event snapshot IDs/hashes when used;
- aggregation unit IDs and level;
- initiating user;
- numerator, denominator, raw and display values;
- performance status, quality status, BLUE reason;
- run status (`running` / `succeeded` / `failed`).

A later formula, mapping, population, or raw-row change does not rewrite a completed run. Lineage remains available from `config_snapshot` and stored foreign keys.

## Binding MNCH formulas

See `docs/project-context/ANALYTICAL_RULES.md` for the complete table. Units:

- PMR and fresh stillbirth rate: per 1,000
- MMR: per 100,000 live births
- Coverage indicators: percent

MV4 uses coefficient 4.3%. BCG/OPV0/HepB birth use 4.85%.

## Phase 3 module and Phase 4 dashboard APIs

`POST /analytics/modules/{anc|intrapartum|immunization|mpdsr}/query` evaluates a module on the shared engine and returns current, comparison, trend, child-unit, freshness, quality, and lineage payloads. It commits its calculation runs.

`POST /analytics/dashboard/query` adds screen kind, population resolution, deterministic insights, facility comparison for districts, direction-aware ranking, the map cohort block, and the export surface, then commits one analysis snapshot. The former GET routes were removed because they created runs (amendment §1).

## Amendment 2026-09-13 engine semantics

- **Common scope.** `resolve_common_scope` resolves every component of a ratio, count or dropout from one scope: all direct rows, or one child cohort of a single aggregation class with complete children and one mapping version. Failures carry `reason_code` (`incompatible_aggregation_scope`, `mixed_levels`, `incomplete_children`, `mixed_mapping_versions`) on the calculated value, and `quality_status` BLUE for scope/quality reasons.
- **Aggregation classes.** `AggregationClass` groups district and city as `district_equivalent`; `top_units_of_class` prevents double counting of nested units of one class.
- **Population year.** `resolve_population_year_rule` uses approved rules only, prefers a programme-specific rule, never borrows another programme's rule, and requires the period kind to be listed in `applies_to_period_kinds`. No fallback year is inferred.
- **Event coverage.** `evaluate_event_coverage` (in `services/event_coverage.py`) verifies MPDSR Tracker provenance before an empty cohort is reported as zero. Calculated values store `event_snapshot_ids` and `event_coverage`; a run's config snapshot lists only that run's event IDs.
- **Interpretation.** `app/domain/interpretation.py` provides `interpret_change` and `rank_units`. Module payloads add `change.interpretation`, `interpretation_reason`, `status_transition`, `classification_mode`, `desired_range`, `thresholds`, `reason_code`, `aggregation_level`, and `event_coverage_status`.

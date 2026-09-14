# Analytical Rules

Authoritative detail and future additions remain in [the canonical handoff](../../ULTIMATE_IDE_HANDOFF_Uganda_Health_Performance_Intelligence_Platform.md). All formulae below are deterministic and versioned. Phase 2 implements them in `backend/app/domain/indicator_catalog.py` and `backend/app/services/calculation.py`. Phase 3 modules and the Phase 4 dashboard call those engines; they do not re-implement formulas. See `docs/architecture/CALCULATION_ENGINE.md`.

## Universal calculation and denominator rules

- Aggregate `SUM(numerators)` and `SUM(denominators)` first, then calculate. Never average child-unit percentages unless a registered indicator explicitly says so.
- Population annual target: `population(year) × coefficient`. For a selected period: `population(year) × coefficient × months_in_period / 12`. Apply only to population-derived denominators, never ANC1, deliveries, live births, or other service/event denominators.
- Current convention: FY2024/25 → 2024 population; FY2025/26 → 2025 population. Configuration, not embedded code, resolves this. These rules cover **full financial years only**. Months, quarters and half-years need an explicit approved rule; until one exists their population-derived values are unavailable (`population_rule_missing`).
- Missing is not zero. A missing facility population affects only indicators that require it.
- BLUE represents unsafe interpretation: impossible bounded results, unresolved reconciliation, invalid chronology, missing denominator, N/A/non-assessable, or a comparable quality state. Do not silently cap actual values.

## Aggregation scope (amendment 2026-09-13)

- Aggregation classes: country; region-equivalent (region, sub-region); **district-equivalent (district, city)**; sub-county; facility. Districts and cities are peers.
- A parent value uses either direct rows for **every** component or one complete child cohort of a single class for every component. A direct numerator with a child denominator (or the reverse) is unavailable (`incompatible_aggregation_scope`). Components from different mapping versions are unavailable (`mixed_mapping_versions`).
- Child cohorts never mix classes (district + facility is `mixed_levels`), never double-count nested units of one class, and a missing child makes the parent `incomplete_children`, not a partial sum.
- Parent populations come from a direct approved value or one complete district/city cohort of the same approved version. Facility catchment entries are facility-only.

## Interpretation and ranking (amendment 2026-09-13)

- Improvement is decided by the approved classification mode: higher-is-better modes improve upward; lower-is-better modes (including teenage pregnancy and MMR) improve downward; desired-range modes improve when the distance to the range shrinks. Changes are compared at display precision.
- BLUE or missing current/comparison values, unclassified (TBD) indicators and neutral counts are `not_interpreted`; only the numeric change is shown.
- Rankings order by the same rule, exclude BLUE, missing and non-assessable units into separate lists, and never rank unclassified indicators, PMR, fresh stillbirth rate, MMR or any MPDSR indicator.

## MPDSR zero and cause rules (amendment 2026-09-13)

- An empty event cohort is a verified zero only with successful, complete, current Tracker coverage whose window spans the cohort and its follow-up period (notification +1 day, review +7 days, counts through the extraction date). Otherwise the count is unknown with a stated reason.
- Cause patterns: structured categories only; country/region/sub-region only; MPDSR programme scope plus `view_mpdsr_events`; an approved minimum cell count; categories from a single reporting unit suppressed. Without the approved minimum, causes are withheld.

## ANC

| Indicator | Deterministic formula | Green | Yellow | Red |
|---|---|---:|---:|---:|
| ANC1 coverage | `ANC1 / (population × 5%) × 100` | ≥95% | 75.0–94.9% | <75% |
| First-trimester ANC | `ANC1 first trimester / ANC1 × 100` | ≥45% | 30.0–44.9% | <30% |
| ANC4 coverage | `ANC4 / (population × 5%) × 100` | ≥75% | 50.0–74.9% | <50% |
| ANC8 coverage | `ANC8 / (population × 5%) × 100` | ≥15% | 7.0–14.9% | <7% |
| IPT3 coverage | `IPT3 / (population × 5%) × 100` | ≥75% | 50.0–74.9% | <50% |
| Hb testing | `Hb tested / ANC1 × 100` | ≥75% | 50.0–74.9% | <50% |
| IFA (≥30 tablets) | `women receiving ≥30 IFA / ANC1 × 100` | ≥95% | 75.0–94.9% | <75% |
| Obstetric ultrasound | `ultrasound / ANC1 × 100` | ≥75% | 50.0–74.9% | <50% |
| Teenage pregnancy | `(ANC1 <15 + ANC1 age 15–19) / ANC1 × 100` | <5% | 5.0–12.9% | ≥13% |

Teenage pregnancy is inverse. IFA over 100% remains visible and carries a definition/reporting quality flag.

## Intrapartum and newborn

| Indicator | Deterministic formula | Green | Yellow | Red | BLUE / caveat |
|---|---|---:|---:|---:|---|
| Institutional delivery | `deliveries / (population × 4.85%) × 100` | ≥65% | 50.0–64.9% | <50% | May legitimately exceed 100% from catchment/referral patterns; do not automatically BLUE it. |
| Caesarean section | `CS / deliveries × 100` | 5.0–15.0% | 3.0–4.9% or 15.1–20.0% | <3.0% or >20.0% | Range indicator. |
| KMC | supplied direct percentage | 95.0–100.0% | 75.0–94.9% | <75% | >100% is BLUE. |
| Successful resuscitation | `successfully resuscitated / birth asphyxia cases × 100` | 90.0–100.0% | 70.0–89.9% | <70% | >100% is BLUE; denominator zero is N/A. |
| PMR | `(fresh SB + macerated SB + newborn deaths) / deliveries × 1,000` | ≤12 | >12–20 | >20 | Rate per 1,000, never %. |
| Fresh stillbirth rate | `fresh SB / deliveries × 1,000` | ≤5 | >5–10 | >10 | Rate per 1,000, never %. |
| MMR | `maternal deaths / live births × 100,000` | ≤183 | 184–300 | >300 | Ratio per 100,000 live births, never %. |

Mortality indicators are inverse. Small-number rates show event counts and must not support ungrounded causal claims.

## Immunization and child health

Coverage: `doses administered / (population × target coefficient × months_in_period / 12) × 100`.

- 4.85%: BCG, OPV0, hepatitis-B birth dose.
- 4.3%: OPV1–3; DPT-HepB-Hib1–3; RotaV1–2; PCV1–3; IPV1–2; measles-rubella; yellow fever; malaria vaccine doses MV1, MV2, MV3, **and MV4**.
- Other coefficients: Td women 15–49 23%; HPV girls 1.53%; Vitamin A 6–11 months 1.93%; Vitamin A/deworming 12–59 months 16.2%; deworming 1–14 years 49.3%; under-5 20.5%.
- Dropout: `(Dose1 − FinalDose) / Dose1 × 100`; inverse direction. Penta1→Penta3 and MV1→MV4 are examples.
- EPI bands not authoritatively specified remain configurable/TBD, not inferred.

## MPDSR

The core scorecard always combines perinatal and maternal processes. Counts are neutral; percentage cells have RAG/BLUE.

| Group | Formula / definition | Target and status |
|---|---|---|
| Perinatal reported | `fresh SB + macerated SB + newborn deaths` | count |
| Perinatal notified / reviewed | COMPLETED notification/review events in death-date cohort | count |
| Perinatal notification/review coverage | `completed events / reported deaths × 100` | ≥90 green; 75–89.9 yellow; <75 red; >100/reconciliation BLUE |
| Perinatal timely notification | `same or next calendar-day completed notifications / reported × 100` | same bands; label proxy if no timestamp |
| Perinatal timely review | `completed reviews within 0–7 days / reported × 100` | same bands |
| Maternal notified / reviewed | `completed events / reported maternal deaths × 100` | 100 green; 90–99.9 yellow; <90 red; non-assessable BLUE |
| Maternal timely notification / review | same/next-day notification or review within 0–7 days, divided by reported maternal deaths | same 100/90/<90 bands |

Only `COMPLETED` events count as completed. `ACTIVE` displays as **Active (not completed)**. Cohort by death date in the selected period. Flag notification/review before death, line-list > aggregate reported, missing cause, duplicate suspicion, and missing/unverifiable dates. Maternal clinical cause analysis defaults to safer regional/national aggregation for small numbers; never expose identifying combinations or send raw line lists to external AI.

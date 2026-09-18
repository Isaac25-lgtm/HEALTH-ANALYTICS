# Synthetic fixture documentation

All automated tests use in-memory SQLite and synthetic fixtures. None of the following are production inputs.

## Geography names

`UG`, `ACHOLI`, `TESO`, `PADER`, `KITGUM`, `SOROTI`, `PADER_TOWN`, `PADER_HC_III` exist only for permission and aggregation regression. They are not the national hierarchy.

## Users

See `docs/architecture/LOCAL_DEVELOPMENT.md`. Password is `SEED_PASSWORD` / `dev-only-change-me`.

## Identifiers

Test DHIS2 identifiers are labelled `TEST_UID_*` (for example `TEST_UID_ANC1`, `TEST_UID_UG`, `TEST_UID_EVENT_…`). They must never be presented as real mappings.

## Populations

Test helpers insert `TEST_POP` / `TEST_SOURCE_SYNTHETIC` values. Default seed inserts **no** national or facility populations.

## Events

`put_event` writes minimised semantic fields only (dates, status, `event_type`). No names, usernames, or narratives. No real MPDSR line lists are in the repository.

## Aggregation fixture

`tests/test_aggregation_first.py` uses unequal child denominators (80/100 and 10/400) so the parent result is 90/500 = 18%, not the mean of 80% and 2.5%.

## Demonstration dataset (development and test only)

`app/services/demo_data.py` layers an invented dataset on the development seed so the dashboards can
be seen working. `scripts/run_e2e_api.py` calls it; `seed_demo_analytics` refuses to run outside
development and test. **Nothing in it is Ugandan health data, a national population, a DHIS2
identifier or an approved boundary.**

| What it adds | Detail |
|---|---|
| Geography | Fictional sub-counties (Atanga, Kitgum Central, Lagoro, Soroti East, Kamuda) and nine facilities under the existing synthetic districts |
| Population | One approved-status version, `DEMO_SYNTHETIC` / `SYNTHETIC_DEMONSTRATION_FIXTURE`, for non-facility units, 2024–2027 |
| Source values | Facility-level counts for every source key the approved catalogue reads, for FY2024/25, FY2025/26 and FY2026/27, written with source system `synthetic_demo_fixture` |
| Source mappings | `DEMO_<key>` labels at mapping version `demo`, so calculations are not flagged as unmapped |
| Geometry | Stylised invented outlines for the two sub-regions and three districts, source `synthetic_demo_fixture` |

Values are deterministic — no randomness and no clock — so screenshots and tests are stable. They are
shaped only to exercise the approved catalogue: every band, direction and formula still comes from
`indicator_catalog`, and the demonstration layer defines no threshold and no formula.

Deliberate gaps keep the honest-missing behaviour visible: facilities have **no** approved catchment
population (facility screens still show the unavailable state), sub-counties and facilities have
**no** geometry (a district map reports unavailable boundaries rather than borrowing shapes from
another level), and periods before FY2024/25 have no approved population rule, so trends show gaps
rather than invented history.

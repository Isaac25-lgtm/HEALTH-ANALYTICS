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

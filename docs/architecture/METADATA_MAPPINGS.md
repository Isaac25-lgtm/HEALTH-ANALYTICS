# Metadata mappings

DHIS2 UIDs must not appear in calculation functions or UI code. Mappings are administrator-managed, versioned configuration.

## Aggregate mappings (`source_mappings`)

| Field | Purpose |
|---|---|
| `internal_source_key` | Semantic key used by formulas (`ANC1`, `DELIVERIES`, `MV4`, …) |
| `programme_id` | Programme scope |
| `dhis2_item_uid` | Data element or DHIS2 indicator UID |
| `item_kind` | `data_element` or `indicator` |
| `category_option_combo_uid` | Optional COC |
| `aggregation_semantics` | How the source should be summed |
| `mapping_version` | Version label |
| `enabled` | Disabled mappings are not extracted |
| `valid_from` / `valid_to` | Historical validity |
| `notes` | Operator notes |

Unique on `(internal_source_key, mapping_version, programme_id)`.

Default seed does **not** insert production UIDs. Tests use unmistakably labelled `TEST_UID_*` values.

## Event field mappings (`event_field_mappings`)

Configurable semantic fields for Event Analytics and Tracker:

- death date
- notification date
- review date
- event status
- cause fields
- facility/community classification
- event or linkage identifier
- completion state

Each row also stores programme UID, programme-stage UID, source data-element UID, expected type, required/optional, event type, version, and validity.

These mappings are **not production-ready**. Authorised UIDs and confirmed source fields are still open items.

Sensitive fields `name`, `narrative`, `username`, and `clinician` are dropped during persist.

## API

- `GET /mappings` — aggregate mappings; requires `manage_mappings`
- `GET /mappings/events` — event field mappings; requires `manage_mappings`

Ordinary users cannot list mappings.

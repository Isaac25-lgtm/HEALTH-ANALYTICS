# Data-quality rule catalogue

Quality is separate from programme performance. A red result may be valid. A green-looking result may be invalid. The calculated value is not overwritten by the quality classification.

Versioned `quality_rules` rows control execution. A disabled or absent database rule does not run. Seeding copies `QUALITY_RULE_CATALOG` into the table; the engine reads the table, not a hard-coded always-on list.

Flags use a stable fingerprint (rule, subject, period, source, relevant evidence). Repeated detection updates `last_detected_at` and does not create a second open flag. Acknowledgement and resolution history are preserved. A resolved problem may reopen on later detection unless suppressed.

MPDSR event flags are scanned only inside the selected death cohort (or associated dates required by that event type). Events from another year/period are not assigned to the requested period.

Unexpected zero is **not** raised for every reported zero. It requires an enabled rule plus context such as previous non-zero history, a configured high-volume facility/source key, or another configured peer/time-series setting. A valid reported zero remains ordinary.

Ordinary API evidence never includes event UID lists, names, narratives, usernames, clinician identifiers, or raw payloads. Sensitive evidence requires MPDSR programme scope and `view_mpdsr_events`.

## Implemented rules

These scanners run when the matching `quality_rules` row is enabled:

| Code | Category | What it detects |
|---|---|---|
| `BOUNDED_PROPORTION_OVER_100` | validity | Bounded measure >100% |
| `NUMERATOR_GT_DENOMINATOR` | validity | Logically impossible numerator > denominator |
| `MISSING_DENOMINATOR` | completeness | Denominator absent |
| `MISSING_POPULATION` | completeness | Population unavailable; service-derived indicators continue |
| `DENOMINATOR_ZERO` | validity | Non-assessable, not zero percent |
| `NO_DATA_VS_REPORTED_ZERO` | completeness | Missing row is not treated as zero |
| `INCOMPLETE_COMPOSITE` | completeness | Required composite component missing |
| `INCOMPLETE_CHILD_COVERAGE` | completeness | Selected child level is incomplete |
| `INVALID_SOURCE_VALUE` | validity | Nonnumeric/invalid source value rejected |
| `AGGREGATE_EVENT_MISMATCH` | reconciliation | Aggregate and line-list counts differ; cause is not inferred |
| `LINELIST_GT_AGGREGATE` | reconciliation | Line-list exceeds reported deaths; lists possible checks only |
| `ACTIVE_MPDSR_WORKFLOW` | workflow | ACTIVE labelled `Active (not completed)` and excluded from completed numerators |
| `NOTIFICATION_BEFORE_DEATH` | chronology | Notification date before death |
| `REVIEW_BEFORE_DEATH` | chronology | Review date before death |
| `REVIEW_INTERVAL_OUT_OF_RANGE` | timeliness | Review outside 0–7 calendar days |
| `MISSING_CAUSE` | completeness | Completed review without cause documentation |
| `MISSING_CRITICAL_DATE` | completeness | Missing death, notification, or review date |
| `POSSIBLE_DUPLICATE_EVENT` | reconciliation | Shared facility, death date, and type |
| `UNEXPECTED_ZERO` | anomaly | Reported zero with prior non-zero or configured high-volume context |
| `ANOMALOUS_SPIKE_DROP` | anomaly | Only when the enabled rule config supplies a deterministic threshold |
| `STALE_REPORTING` | freshness | Latest expected period older than configured window |
| `STALE_ANALYTICS` | freshness | Event Analytics lags Tracker |
| `MAPPING_MISSING` | metadata | Required semantic mapping absent |
| `MAPPING_AMBIGUOUS` | metadata | Enabled mappings collide |
| `METADATA_DRIFT` | metadata | Mapped identifiers changed between extracts |
| `PARENT_CHILD_RECONCILIATION` | reconciliation | Parent/child mix would double-count |
| `FACILITY_POPULATION_PENDING_APPROVAL` | governance | Catchment value exists but is not approved |
| `SOURCE_FRESHNESS_MISMATCH` | freshness | Event Analytics and Tracker freshness times differ |
| `INCOMPATIBLE_AGGREGATION_SCOPE` | reconciliation | Numerator and denominator do not share one aggregation scope or mapping version (amendment §7) |
| `MPDSR_EVENT_COVERAGE_UNVERIFIED` | completeness | No successful, complete, current, scoped Tracker sync proves the event cohort (amendment §6) |
| `POPULATION_RULE_MISSING` | configuration | No approved period-population rule covers the requested period kind (amendment §4) |

`PARENT_CHILD_RECONCILIATION` compares aggregation classes, so district and city children are peers while a district-plus-facility mix is still flagged. Freshness comparison uses the oldest Event Analytics freshness deterministically.

Explanations are human-readable and paired with machine-readable evidence. The engine does not decide that a mismatch is “definitely duplication” or “definitely under-reporting”.

## APIs

- `GET /quality/flags` — ordinary redacted schema; SQL-filtered by authorised geography and programme
- `GET /quality/flags/{id}` — ordinary redaction by default; sensitive representation requires MPDSR + `view_mpdsr_events`

# Calculation provenance

Every calculated value can be traced to:

- calculation software/release version (`SOFTWARE_VERSION`)
- indicator ID and formula version, plus the complete formula/classification specifications
- geography, level, programme, and period
- numerator and denominator
- population year, selected policy, and either `population_version_id` or `facility_population_entry_id` (never a false national-version attribution for a facility entry)
- source mapping IDs and versions actually used
- raw aggregate row IDs and checksums
- event snapshot IDs/hashes or an approved de-identified cohort manifest when events are used
- source extraction/freshness timestamps
- aggregation unit IDs and level
- initiating user
- calculation-run ID

`CalculatedValue.mapping_version` stores the mapping version that supplied the data, not the formula version, and not a hard-coded `v1` when another version was used.

## Raw data immutability

Refresh supersedes the current row instead of overwriting it.

- `raw_aggregate_values`: unique current row per `(source_system, programme, org_unit, period, internal_source_key, category_option_combo_uid)`
- `raw_event_snapshots`: unique current row per `(event_uid, source_connector)`

Historical rows keep checksum/snapshot hash, extraction time, sync job, and mapping version.

Absence reasons remain distinct: reported zero, no source row, unavailable, mapping failure, invalid value, stale.

## Calculation runs

`calculation_runs.config_snapshot` stores the software version, indicator version IDs, formula/classification specs, raw row IDs, mapping versions, population/facility provenance, aggregation policy, and requested geography/programme/period. Changing a later indicator version, mapping, population file, or raw value does not rewrite an older run. Reproducibility tests assert that the stored lineage still identifies the original source rows after those rows are later mutated.

Failed runs are stored as `failed` and are not presented as complete.

## Amendment 2026-09-13 provenance additions

- Calculated values store `reason_code`, `event_snapshot_ids` and `event_coverage` (the verifying sync job, its window and finish time, or the unverified reason).
- Sync jobs store `window_start` and `window_end`. Freshness snapshots are written after the final status, `finished_at` and duration; `last_success_at`, `source_freshness_at`, `lag_seconds` and `sync_job_id` describe the last successful job, and `detail.last_attempt` describes the latest attempt.
- Analysis snapshots store `idempotency_key` (unique per user) and the original request in `view_config.request`. Identifiers are written into the payload before the row is stored, so the committed snapshot equals the response.
- Population versions store `source_dataset`, `source_file_name`, `source_sha256` and `source_sheet`; population values store `source_unit_name`, `source_unit_type`, `source_region` and `source_column_label`. Reviewed aliases live in `population_source_aliases` with proposer, decider, timestamps and notes.
- Migration `0007_amendment_corrections` adds these columns and preserves existing FY period rules as FY-only.

## MPDSR snapshots

`raw_event_snapshots` is a restricted-event table. Default persist drops names, narratives, usernames, and clinician identifiers. Ordinary APIs do not return raw payloads or event UIDs.

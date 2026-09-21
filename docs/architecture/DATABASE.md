# Database and domain model

Schema is defined in `backend/app/models/__init__.py`. Historical Alembic revisions are **explicit and frozen**:

| Revision | Creates | Source |
|---|---|---|
| `0001_phase1_foundation` | Phase 1 tables only | `backend/alembic/historical/phase1.py` |
| `0002_phase2_engines` | Phase 2 tables plus `sync_job_id` columns | `backend/alembic/historical/phase2.py` |
| `0003_phase12_corrections` | Sessions, grant validity, provenance, fingerprints, unique current indexes | `backend/alembic/historical/phase12_corrections.py` |
| `0004_phase12_audit_fixes` | Programme identity on raw aggregates; current-geometry uniqueness | `backend/alembic/historical/phase12_audit_fixes.py` |
| `0005_phase567_ai_publishing` | Export artifact columns and AI request metadata | `backend/alembic/versions/0005_phase567_ai_publishing.py` |
| `0006_corrective_snapshots` | Analytical snapshots, event programme binding, exact-run columns | `backend/alembic/versions/0006_corrective_snapshots.py` |
| `0007_amendment_corrections` | Request keys, explicit period-rule scope, population source identity and aliases, sync windows, value reason codes | `backend/alembic/versions/0007_amendment_corrections.py` |
| `0008_export_queue_durability` | One live export job per user + snapshot + type, attempts, dispatch and claim state, widened key | `backend/alembic/versions/0008_export_queue_durability.py` |
| `0009_retention_artifacts` | `maintenance_runs`, `maintenance_locks`, `export_artifacts`, artifact expiry on export jobs, retention indexes | `backend/alembic/versions/0009_retention_artifacts.py` |
| `0010_denominator_provenance` | `calculated_values.denominator_provenance` | `backend/alembic/versions/0010_denominator_provenance.py` |
| `0011_population_import_staging` | `population_import_batches`, `population_import_rows` | `backend/alembic/versions/0011_population_import_staging.py` |
| `0012_population_staging_identity` | `population_import_batches.reference_fingerprint` and unique staging identity (checksum, importer version, fingerprint) | `backend/alembic/versions/0012_population_staging_identity.py` |
| `0013_org_mapping_guard` | PostgreSQL exclusion constraint preventing overlapping effective intervals for one DHIS2 organisation-unit UID | `backend/alembic/versions/0013_org_mapping_guard.py` |

**Current head: `0013_org_mapping_guard`.** Revisions 0001–0008 are historical and immutable; add forward revisions only.

Historical files must not import application ORM models, call `Base.metadata.create_all()`, or copy live columns. Importing a future model must not change what 0001 or 0002 creates.

Revision ids must be at most 32 characters (PostgreSQL `alembic_version.version_num`); a static test enforces it.

## Reference bootstrap (production) versus development seed

A migrated database holds schema only. `python scripts/bootstrap_reference_data.py` (service `app/services/reference_bootstrap.py`) then creates the approved, non-secret reference configuration if missing: programmes MNCH/EPI/MPDSR, roles and role permissions, the indicator catalogue with undated `v1` versions, the quality-rule catalogue, D-045 period rules for 2024–2030, and a neutral `UG` country root. It creates no users, sub-national geography, DHIS2 UIDs, raw values, populations or boundaries. Rows that differ from the approved reference are reported as conflicts and nothing is written; PostgreSQL releases are serialised with `pg_advisory_xact_lock`.

`seed_reference_data()` (development and tests only) runs the same bootstrap and adds synthetic geography (`ACHOLI`, `TESO`, `PADER`, `KITGUM`, `SOROTI`, `PADER_TOWN`, `PADER_HC_III`) and synthetic users. No production populations, DHIS2 UIDs, indicator result values, or MPDSR cases are stored in either.

## Pre-production migration-history correction

No shared or staging database that had already applied the previous dynamic revisions was identified in this repository.

- **Fresh databases:** run Alembic from empty to head (`0013_org_mapping_guard`), then the reference bootstrap. Rewritten 0001/0002 are the intended history.
- **A database already stamped at the old 0002 head:** apply only `0003_phase12_corrections`. Do not drop that database and do not replay 0001/0002.
- **A database created by the old dynamic 0001** (which could have created later tables): treat it as already containing later objects; stamp/upgrade with care and do not assume it can be deleted.

The 2026-09-12 migration gate used a newly created disposable PostgreSQL 18.1 cluster (trust auth, port 55433, role `hpip_verify`) and created/dropped only `hpip_p18_alembic_verify`. The existing localhost:5432 instance was not mutated. That isolated cluster is not a shared project database and was stopped after verification.

## Identity and authorisation

- `users`, `roles`, `user_roles`
- `role_permissions`, `user_permissions`
- `user_geography_scopes`, `user_programme_scopes` — `is_active`, `valid_from`, `valid_to`
- `auth_sessions` (JTI + CSRF), `login_attempts`
- `audit_log` (secrets and event `data_values` are redacted)

## Geography

- `org_units`: stable UUID, code, name, `level_type`, parent, materialized `path`, active, valid-from/to, optional facility metadata
- Levels: country, region, sub_region, district, city, sub_county, facility
- `org_unit_mappings`: external/DHIS2 UID mapping with validity dates
- `org_unit_groups` / `org_unit_group_members`
- `geometries`: GeoJSON payload now; PostGIS column can be added when the extension is enabled

## Programme and indicators

- `programmes`, `indicators`, `indicator_versions`, `indicator_source_mappings`
- At most one current indicator version per indicator (`uq_indicator_versions_current`)
- Version rows hold typed `formula_spec` / `classification_spec`, coefficient, multiplier, unit, direction, RAG/BLUE bands, aggregation method, period-adjustment flag, methodology text, validity
- `period_population_rules`: approved rules per D-045 — FY2024/25–FY2029/30 map to their base year for the FY and its child months/quarters/half-years; calendar years 2024–2030 map to themselves. Nothing beyond the approved source horizon is seeded.

## Population

- `population_versions`, `population_values` (org unit × year × version)
- `facility_population_entries`: catchment history, estimated/official type, entered-by, approval, rejection, supersession, `is_current_approved` (partial unique on org unit + year)
- `population_import_batches` / `population_import_rows`: governed staging of an approved source (checksum, importer version, national and broad-region totals, reference scope) with every row's match state and review state. Staged rows are never denominators.
- `population_source_aliases`: reviewed crosswalk decisions

## Phase 2 mappings, sync, and provenance

- `source_mappings`, `event_field_mappings`
- `sync_jobs` (including `idempotency_key`, `page_limit_reached`), `freshness_snapshots`, `operational_events`
- `quality_rules` — enabled/versioned rows control execution
- `raw_aggregate_values` — current unique per source system, org unit, period, internal source key, and category option combo
- `raw_event_snapshots` — restricted-event privacy class
- `calculation_runs`, `calculated_values` — performance and quality statuses stored separately; facility entry ID is distinct from national population version
- `data_quality_flags` — fingerprint, first/last detected, acknowledgement, resolution
- `saved_views`, `export_jobs`, `ai_requests` remain Phase 4–6 tables only

Historical calculation rows reference indicator version, population version or facility entry, raw row IDs, and mapping versions so later configuration changes do not silently rewrite old results. `denominator_provenance` records period kind, parent FY, population year, fraction, coefficient and annual/adjusted target, so a snapshot stays explainable after its raw rows are purged.

## Retention and maintenance

- `maintenance_runs`: one row per purge policy pass — counts, cutoff, status, safe error code, source, software version. Never deleted content, event UIDs or paths.
- `maintenance_locks`: provider-neutral lease so two purge processes never share a policy. The holder renews it with a holder-checked update inside every batch transaction.
- `maintenance_runs` and `operational_events` are themselves purged after `OPERATIONAL_RECORD_RETENTION_DAYS` (90, engineering default pending owner confirmation).
- `population_import_batches.reference_fingerprint`: SHA-256 of the candidate district/city hierarchy, approved aliases and `POPULATION_HIERARCHY_APPROVAL_REFERENCE`. Re-staging the same checksum, importer version and fingerprint reuses the batch. `review_status` moves from `pending_review` to `reviewed` or `rejected` only through `review_staged_batch` (second reviewer with `approve_population`, recorded reason, audited); `reviewed` requires an authoritative, fully resolved batch. Review never creates or approves population values.
- `export_artifacts`: temporary export bytes for deployments without a shared disk, bounded by `EXPORT_ARTIFACT_MAX_BYTES` and purged after 24 hours. `export_jobs` keeps checksum, size, media type and `artifact_deleted_at` for 90 days.
- Retention windows and purge order are described in `docs/DEPLOYMENT.md` (section 4).

## Connection settings

`DATABASE_URL` is the runtime (pooled) URL; `MIGRATION_DATABASE_URL` optionally supplies a direct URL that Alembic prefers. Plain `postgresql://` and `postgres://` URLs are normalised to `postgresql+psycopg`; other PostgreSQL drivers are rejected. Alembic builds its engine through `create_migration_engine` with the same TLS mode, connect timeout and application name, and `NullPool`. An `sslmode` in the URL takes precedence over `DB_SSLMODE`; a conflict between them is a configuration error. Pools are small and configurable (`DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_RECYCLE_SECONDS`, `DB_POOL_TIMEOUT_SECONDS`, `DB_CONNECT_TIMEOUT_SECONDS`), with pre-ping enabled. Production requires TLS (`DB_SSLMODE=require`) unless `DB_REQUIRE_SSL=false` is set for a private network.

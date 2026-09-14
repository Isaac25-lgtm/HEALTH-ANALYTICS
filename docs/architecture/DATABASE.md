# Database and domain model

Schema is defined in `backend/app/models/__init__.py`. Historical Alembic revisions are **explicit and frozen**:

| Revision | Creates | Source |
|---|---|---|
| `0001_phase1_foundation` | Phase 1 tables only | `backend/alembic/historical/phase1.py` |
| `0002_phase2_engines` | Phase 2 tables plus `sync_job_id` columns | `backend/alembic/historical/phase2.py` |
| `0003_phase12_corrections` | Sessions, grant validity, provenance, fingerprints, unique current indexes | `backend/alembic/historical/phase12_corrections.py` |
| `0004_phase12_audit_fixes` | Programme identity on raw aggregates; current-geometry uniqueness | `backend/alembic/historical/phase12_audit_fixes.py` |
| `0005_phase567_ai_publishing` | Export artifact columns and AI request metadata | `backend/alembic/versions/0005_phase567_ai_publishing.py` |

Historical files must not import application ORM models, call `Base.metadata.create_all()`, or copy live columns. Importing a future model must not change what 0001 or 0002 creates.

No production populations, DHIS2 UIDs, indicator result values, or MPDSR cases are stored in seeds. Development geography uses synthetic codes (`UG`, `ACHOLI`, `PADER`, `PADER_HC_III`, plus sibling `TESO` for isolation tests).

## Pre-production migration-history correction

No shared or staging database that had already applied the previous dynamic revisions was identified in this repository.

- **Fresh databases:** run Alembic from empty to `0005_phase567_ai_publishing`. Rewritten 0001/0002 are the intended history. 0005 only adds export/AI columns.
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
- `period_population_rules`: FY2024/25 → 2024 and FY2025/26 → 2025 as configuration

## Population

- `population_versions`, `population_values` (org unit × year × version)
- `facility_population_entries`: catchment history, estimated/official type, entered-by, approval, rejection, supersession, `is_current_approved` (partial unique on org unit + year)

## Phase 2 mappings, sync, and provenance

- `source_mappings`, `event_field_mappings`
- `sync_jobs` (including `idempotency_key`, `page_limit_reached`), `freshness_snapshots`, `operational_events`
- `quality_rules` — enabled/versioned rows control execution
- `raw_aggregate_values` — current unique per source system, org unit, period, internal source key, and category option combo
- `raw_event_snapshots` — restricted-event privacy class
- `calculation_runs`, `calculated_values` — performance and quality statuses stored separately; facility entry ID is distinct from national population version
- `data_quality_flags` — fingerprint, first/last detected, acknowledgement, resolution
- `saved_views`, `export_jobs`, `ai_requests` remain Phase 4–6 tables only

Historical calculation rows reference indicator version, population version or facility entry, raw row IDs, and mapping versions so later configuration changes do not silently rewrite old results.

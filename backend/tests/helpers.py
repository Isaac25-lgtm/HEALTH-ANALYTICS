from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select

from app.domain.enums import (
    ApprovalStatus,
    ConnectorType,
    JobStatus,
    MappingSourceSystem,
    PeriodRuleScope,
    PopulationType,
)
from app.domain.indicator_catalog import INDICATOR_CATALOG
from app.models import (
    EventFieldMapping,
    OrgUnitMapping,
    PeriodPopulationRule,
    PopulationValue,
    PopulationVersion,
    Programme,
    RawAggregateValue,
    RawEventSnapshot,
    SourceMapping,
    SyncJob,
)

TEST_MPDSR_PROGRAM_UID = "TEST_UID_MPDSR_PROGRAM"


def put_mpdsr_coverage(
    session,
    org_unit,
    *,
    window_start,
    window_end,
    finished_at=None,
    status: str = JobStatus.SUCCEEDED.value,
    page_limit_reached: bool = False,
    rejected_count: int = 0,
    mapping_version: str = "v1",
    with_mapping: bool = True,
):
    """Synthetic MPDSR Tracker sync provenance. Not a production job or identifier."""
    programme = session.scalar(select(Programme).where(Programme.code == "MPDSR"))
    if with_mapping:
        existing = session.scalar(
            select(EventFieldMapping).where(
                EventFieldMapping.programme_id == programme.id,
                EventFieldMapping.program_uid == TEST_MPDSR_PROGRAM_UID,
                EventFieldMapping.mapping_version == mapping_version,
            )
        )
        if existing is None:
            session.add(
                EventFieldMapping(
                    programme_id=programme.id,
                    program_uid=TEST_MPDSR_PROGRAM_UID,
                    source_data_element_uid="TEST_UID_DE_DEATH_DATE",
                    internal_semantic_field="death_date",
                    event_type="perinatal_notification",
                    mapping_version=mapping_version,
                    enabled=True,
                )
            )
            session.flush()
    finished = finished_at or datetime.now(UTC)
    job = SyncJob(
        job_type=ConnectorType.TRACKER.value,
        status=status,
        org_unit_id=org_unit.id,
        programme_id=programme.id,
        mapping_version=mapping_version,
        started_at=finished,
        finished_at=finished,
        page_limit_reached=page_limit_reached,
        rejected_count=rejected_count,
        window_start=window_start,
        window_end=window_end,
    )
    session.add(job)
    session.flush()
    return job


def put_period_rule(
    session,
    key: str,
    year: int,
    *,
    kinds: list[str],
    scope: str = PeriodRuleScope.FINANCIAL_YEAR.value,
    programme_id=None,
    approval_status: str = ApprovalStatus.APPROVED.value,
):
    """Explicit test period-population rule. Production rules require owner approval."""
    row = session.scalar(
        select(PeriodPopulationRule).where(
            PeriodPopulationRule.financial_year_key == key,
            PeriodPopulationRule.programme_id.is_(None)
            if programme_id is None
            else PeriodPopulationRule.programme_id == programme_id,
        )
    )
    if row is None:
        row = PeriodPopulationRule(financial_year_key=key, programme_id=programme_id, population_year=year)
        session.add(row)
    row.population_year = year
    row.scope_kind = scope
    row.applies_to_period_kinds = kinds
    row.approval_status = approval_status
    session.flush()
    return row


def _programme_id_for_key(session, key: str, programme_code: str | None = None):
    codes: set[str] = set()
    for indicator in INDICATOR_CATALOG:
        spec = indicator.get("formula_spec") or {}
        source_keys = set(spec.get("source_keys") or [])
        source_keys.update(spec.get("numerator_keys") or [])
        source_keys.update((spec.get("denominator") or {}).get("source_keys") or [])
        for singular in ("source_key", "first_key", "final_key"):
            if spec.get(singular):
                source_keys.add(spec[singular])
        if key in source_keys:
            codes.add(indicator["programme"])
    if programme_code and programme_code in codes:
        preferred_code = programme_code
    elif not codes:
        return None
    else:
        preferred_code = "MNCH" if "MNCH" in codes else sorted(codes)[0]
    row = session.scalar(select(Programme).where(Programme.code == preferred_code))
    return row.id if row else None


def put_raw(
    session,
    org_unit,
    period: str,
    key: str,
    value: float | None,
    *,
    absence: str | None = None,
    programme_id=None,
    programme_code: str | None = None,
):
    resolved_programme_id = programme_id or _programme_id_for_key(session, key, programme_code)
    existing = session.scalar(
        select(RawAggregateValue).where(
            RawAggregateValue.programme_id == resolved_programme_id,
            RawAggregateValue.org_unit_id == org_unit.id,
            RawAggregateValue.period == period,
            RawAggregateValue.internal_source_key == key,
            RawAggregateValue.is_current.is_(True),
        )
    )
    if existing is not None:
        existing.is_current = False
        session.flush()
    row = RawAggregateValue(
        source_system="synthetic_test",
        programme_id=resolved_programme_id,
        org_unit_id=org_unit.id,
        period=period,
        source_metric_id=f"TEST_UID_{key}",
        internal_source_key=key,
        dhis2_item_uid=f"TEST_UID_{key}",
        value=value,
        extracted_at=datetime.now(UTC),
        mapping_version="v1",
        absence_reason=absence,
        is_current=True,
        checksum="test",
    )
    session.add(row)
    session.flush()
    return row


def put_population(session, org_unit, year: int, value: float, *, code: str = "TEST_POP"):
    version = session.scalar(select(PopulationVersion).where(PopulationVersion.code == code))
    if version is None:
        version = PopulationVersion(
            code=code,
            name="Synthetic test population — not a national figure",
            source_name="TEST_SOURCE_SYNTHETIC",
            population_type=PopulationType.PROJECTION.value,
            approval_status=ApprovalStatus.APPROVED.value,
        )
        session.add(version)
        session.flush()
    existing = session.scalar(
        select(PopulationValue).where(
            PopulationValue.version_id == version.id,
            PopulationValue.org_unit_id == org_unit.id,
            PopulationValue.year == year,
        )
    )
    if existing is not None:
        existing.population = value
        session.flush()
        return version
    session.add(
        PopulationValue(
            version_id=version.id,
            org_unit_id=org_unit.id,
            year=year,
            population=value,
        )
    )
    session.flush()
    return version


def map_ou(session, org_unit, uid: str):
    row = OrgUnitMapping(
        org_unit_id=org_unit.id,
        source_system=MappingSourceSystem.DHIS2.value,
        external_uid=uid,
    )
    session.add(row)
    session.flush()
    return row


def map_source(session, programme_id, key: str, uid: str):
    row = SourceMapping(
        internal_source_key=key,
        programme_id=programme_id,
        dhis2_item_uid=uid,
        item_kind="data_element",
        mapping_version="v1",
        enabled=True,
        notes="Synthetic TEST_UID mapping. Not a production identifier.",
    )
    session.add(row)
    session.flush()
    return row


def put_event(session, org_unit, **kwargs):
    payload = {
        "event_uid": kwargs.get("event_uid", f"TEST_UID_EVENT_{uuid4().hex[:8]}"),
        "programme_id": kwargs.get("programme_id"),
        "program_uid": kwargs.get("program_uid"),
        "source_connector": kwargs.get("source_connector", "tracker"),
        "org_unit_id": org_unit.id,
        "status": kwargs.get("status", "COMPLETED"),
        "death_date": kwargs.get("death_date"),
        "notification_date": kwargs.get("notification_date"),
        "review_date": kwargs.get("review_date"),
        "data_values": kwargs.get("data_values") or {},
        "extracted_at": datetime.now(UTC),
        "is_current": True,
        "privacy_class": "restricted_event",
    }
    row = RawEventSnapshot(**payload)
    session.add(row)
    session.flush()
    return row

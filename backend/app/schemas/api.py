from datetime import date
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import ConnectorType, PopulationType, ProgrammeCode


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=8, max_length=128)


class SessionLoginResponse(BaseModel):
    ok: bool = True
    csrf_token: str


class TokenResponse(BaseModel):
    """Deprecated browser contract. Access tokens are cookie-only."""

    ok: bool = True
    csrf_token: str | None = None


class OrgUnitSummary(BaseModel):
    id: UUID
    code: str
    name: str
    level_type: str
    parent_id: UUID | None = None
    path: str


class CurrentContextResponse(BaseModel):
    user_id: UUID
    username: str
    display_name: str
    role_codes: list[str]
    landing_org_unit: OrgUnitSummary | None
    landing_org_units: list[OrgUnitSummary]
    geography_scopes: list[OrgUnitSummary]
    geography_entry_units: list[OrgUnitSummary] = Field(default_factory=list)
    available_geography_levels: list[str] = Field(default_factory=list)
    programmes: list[str]
    actions: list[str]
    identity_provider: str = Field(
        description="local_dev until an approved identity provider replaces development users."
    )


class HealthResponse(BaseModel):
    status: str
    service: str
    phase: str


class ReadyResponse(BaseModel):
    status: str
    database: str
    dhis2: str = "not_configured"
    queue: str = "unconfigured"
    redis: str = "unconfigured"
    config_errors: list[str] = []


class ErrorBody(BaseModel):
    code: str
    message: str


class ExportAcceptedResponse(BaseModel):
    job_id: UUID
    status: str
    message: str
    reused: bool = False
    dispatch_state: str | None = None
    error_code: str | None = None
    retryable: bool = False
    retry_scheduled: bool = False
    attempt_count: int = 0


class ProgrammeSummary(BaseModel):
    code: str
    name: str
    sensitive: bool


class PopulationResolveResponse(BaseModel):
    status: str
    population: float | None
    year: int | None
    version_id: UUID | None
    version_code: str | None
    source: str | None
    policy: str
    reason: str | None
    period_fraction: float | None = None
    selection_reason: str | None = None
    facility_population_entry_id: UUID | None = None
    approval_status: str | None = None
    population_type: str | None = None


class FacilityPopulationRequest(BaseModel):
    org_unit_id: UUID
    year: int = Field(ge=2000, le=2100)
    population: float = Field(gt=0, lt=1_000_000_000)
    source_name: str = Field(min_length=1, max_length=255)
    population_type: PopulationType = PopulationType.FACILITY_CATCHMENT_ESTIMATE
    reason: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=2000)


class FacilityPopulationDecisionRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class PopulationImportRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    org_unit_code: str = Field(min_length=1, max_length=80)
    year: int = Field(ge=2000, le=2100)
    population: float = Field(gt=0, lt=1_000_000_000)


class PopulationVersionImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    name: str = Field(min_length=1, max_length=255)
    source_name: str = Field(min_length=1, max_length=255)
    source_document: str | None = Field(default=None, max_length=500)
    population_type: PopulationType
    valid_from: date | None = None
    valid_to: date | None = None
    notes: str | None = Field(default=None, max_length=2000)
    rows: list[PopulationImportRow] = Field(min_length=1, max_length=10_000)


class PopulationVersionResponse(BaseModel):
    id: UUID
    code: str
    name: str
    source_name: str
    population_type: str
    approval_status: str
    row_count: int


class IndicatorSummary(BaseModel):
    id: UUID
    code: str
    name: str
    programme: str
    current_version: str | None


class IndicatorVersionSummary(BaseModel):
    id: UUID
    formula_version: str
    unit: str
    multiplier: float
    denominator_type: str
    period_adjustment: bool
    is_current: bool
    methodology_text: str | None


class CalculationRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    org_unit_id: UUID
    period: str
    programme: ProgrammeCode
    indicator_codes: list[str] | None = Field(default=None, max_length=200)


class CalculationValueResponse(BaseModel):
    indicator_code: str
    formula_version: str
    numerator: float | None
    denominator: float | None
    raw_value: float | None
    display_value: str | None
    unit: str | None
    status: str | None
    performance_status: str | None
    quality_status: str | None
    population_year: int | None
    calculation_run_id: UUID
    blue_reason: str | None = None
    population_version_id: UUID | None = None
    facility_population_entry_id: UUID | None = None
    population_source: str | None = None
    population_approval_status: str | None = None
    population_type: str | None = None
    aggregation_policy: str | None = None
    mapping_version: str | None = None


class CalculationRunResponse(BaseModel):
    id: UUID
    status: str
    period: str
    org_unit_id: UUID | None
    quality_flag_count: int
    config_snapshot: dict | None
    values: list[CalculationValueResponse] = []


class OrdinaryQualityFlagResponse(BaseModel):
    id: UUID
    rule_id: str
    category: str | None
    severity: str
    status: str
    explanation: str | None
    period: str | None
    org_unit_id: UUID | None
    programme_id: UUID | None = None
    evidence: dict | None


class SensitiveQualityFlagResponse(OrdinaryQualityFlagResponse):
    event_uid: str | None = None


class QualityFlagResponse(OrdinaryQualityFlagResponse):
    event_uid: str | None = None


class DashboardQueryRequest(BaseModel):
    """Explicit analytical execution. Creates calculation runs and one committed snapshot."""

    model_config = ConfigDict(extra="forbid")

    org_unit_id: UUID
    period: str = Field(min_length=4, max_length=20)
    module: str | None = Field(default=None, max_length=40)
    comparison_period: str | None = Field(default=None, max_length=20)
    selected_indicator: str | None = Field(default=None, max_length=80)
    request_key: str | None = Field(default=None, min_length=8, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")


class ModuleQueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    org_unit_id: UUID
    period: str = Field(min_length=4, max_length=20)
    comparison_period: str | None = Field(default=None, max_length=20)
    include_children: bool = True


class SyncJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    org_unit_id: UUID
    period: str
    programme: ProgrammeCode
    job_type: ConnectorType
    mapping_version: str = Field(default="v1", min_length=1, max_length=40)
    idempotency_key: str | None = Field(default=None, max_length=80)
    event_window_end: date | None = Field(
        default=None,
        description=(
            "Tracker jobs only: last event date to request. Must not precede the period end or be in the future. "
            "Needed to prove completion counts through the extraction date."
        ),
    )


class DashboardRefreshRequest(BaseModel):
    """Refresh live aggregate data for a dashboard module.

    Mapping selection remains server-owned: browsers never choose a DHIS2 UID or silently
    nominate one of several mapping versions.
    """

    model_config = ConfigDict(extra="forbid")

    org_unit_id: UUID
    period: str = Field(min_length=4, max_length=20)
    module: str = Field(min_length=1, max_length=40)
    idempotency_key: str | None = Field(default=None, max_length=80)


class SyncJobResponse(BaseModel):
    id: UUID
    job_type: str
    status: str
    requested_count: int
    received_count: int
    stored_count: int
    rejected_count: int
    flagged_count: int
    retry_count: int
    error_code: str | None
    error_message: str | None
    source_freshness_at: str | None = None


class MappingResponse(BaseModel):
    id: UUID
    internal_source_key: str
    mapping_version: str
    enabled: bool
    item_kind: str
    dhis2_item_uid: str | None
    notes: str | None

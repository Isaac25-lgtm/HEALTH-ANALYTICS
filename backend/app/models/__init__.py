"""SQLAlchemy models — identity, geography, programmes, population, provenance, audit."""

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    false,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.domain.enums import (
    AggregationMethod,
    AliasDecisionStatus,
    ApprovalStatus,
    EventStatus,
    JobStatus,
    MappingSourceSystem,
    PeriodRuleScope,
    PrivacyClass,
    QualitySeverity,
    QualityStatus,
)


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    username: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_system_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    identity_provider: Mapped[str] = mapped_column(
        String(50), default="local_dev", nullable=False
    )
    external_subject: Mapped[str | None] = mapped_column(String(255))

    roles: Mapped[list["Role"]] = relationship(
        secondary="user_roles", back_populates="users"
    )
    geography_scopes: Mapped[list["UserGeographyScope"]] = relationship(back_populates="user")
    programme_scopes: Mapped[list["UserProgrammeScope"]] = relationship(back_populates="user")
    extra_permissions: Mapped[list["UserPermission"]] = relationship(back_populates="user")


class Role(Base, TimestampMixin):
    __tablename__ = "roles"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    users: Mapped[list[User]] = relationship(secondary="user_roles", back_populates="roles")
    permissions: Mapped[list["RolePermission"]] = relationship(back_populates="role")


class UserRole(Base):
    __tablename__ = "user_roles"
    __table_args__ = (UniqueConstraint("user_id", "role_id"),)

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    role_id: Mapped[UUID] = mapped_column(ForeignKey("roles.id"), primary_key=True)


class RolePermission(Base):
    __tablename__ = "role_permissions"
    __table_args__ = (UniqueConstraint("role_id", "action"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    role_id: Mapped[UUID] = mapped_column(ForeignKey("roles.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(80), nullable=False)

    role: Mapped[Role] = relationship(back_populates="permissions")


class UserPermission(Base):
    __tablename__ = "user_permissions"
    __table_args__ = (UniqueConstraint("user_id", "action"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(80), nullable=False)

    user: Mapped[User] = relationship(back_populates="extra_permissions")


class UserGeographyScope(Base, TimestampMixin):
    __tablename__ = "user_geography_scopes"
    __table_args__ = (UniqueConstraint("user_id", "org_unit_id"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    org_unit_id: Mapped[UUID] = mapped_column(ForeignKey("org_units.id"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)

    user: Mapped[User] = relationship(back_populates="geography_scopes")
    org_unit: Mapped["OrgUnit"] = relationship()


class UserProgrammeScope(Base, TimestampMixin):
    __tablename__ = "user_programme_scopes"
    __table_args__ = (UniqueConstraint("user_id", "programme_id"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    programme_id: Mapped[UUID] = mapped_column(ForeignKey("programmes.id"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)

    user: Mapped[User] = relationship(back_populates="programme_scopes")
    programme: Mapped["Programme"] = relationship()


class AuthSession(Base, TimestampMixin):
    __tablename__ = "auth_sessions"
    __table_args__ = (UniqueConstraint("jti"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    jti: Mapped[str] = mapped_column(String(64), nullable=False)
    csrf_token: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip_address: Mapped[str | None] = mapped_column(String(80))


class LoginAttempt(Base):
    __tablename__ = "login_attempts"
    __table_args__ = (Index("ix_login_attempts_username_created", "username", "created_at"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    username: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    succeeded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class OrgUnit(Base, TimestampMixin):
    __tablename__ = "org_units"
    __table_args__ = (UniqueConstraint("code"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    level_type: Mapped[str] = mapped_column(String(40), nullable=False)
    parent_id: Mapped[UUID | None] = mapped_column(ForeignKey("org_units.id"), index=True)
    path: Mapped[str] = mapped_column(String(1000), nullable=False, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    ownership: Mapped[str | None] = mapped_column(String(80))
    facility_level: Mapped[str | None] = mapped_column(String(40))

    parent: Mapped["OrgUnit | None"] = relationship(remote_side="OrgUnit.id")
    mappings: Mapped[list["OrgUnitMapping"]] = relationship(back_populates="org_unit")


class OrgUnitMapping(Base, TimestampMixin):
    __tablename__ = "org_unit_mappings"
    __table_args__ = (UniqueConstraint("source_system", "external_uid", "valid_from"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    org_unit_id: Mapped[UUID] = mapped_column(ForeignKey("org_units.id"), nullable=False)
    source_system: Mapped[str] = mapped_column(String(40), default=MappingSourceSystem.DHIS2.value)
    external_uid: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
        comment=(
            "External identifier such as a DHIS2 organisation-unit UID. "
            "Never hard-code production UIDs."
        ),
    )
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)

    org_unit: Mapped[OrgUnit] = relationship(back_populates="mappings")


class OrgUnitGroup(Base, TimestampMixin):
    """Future analytical groupings (catchments, partners, historical regions)."""

    __tablename__ = "org_unit_groups"
    __table_args__ = (UniqueConstraint("code"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    group_type: Mapped[str] = mapped_column(String(80), nullable=False)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class OrgUnitGroupMember(Base):
    __tablename__ = "org_unit_group_members"
    __table_args__ = (UniqueConstraint("group_id", "org_unit_id"),)

    group_id: Mapped[UUID] = mapped_column(ForeignKey("org_unit_groups.id"), primary_key=True)
    org_unit_id: Mapped[UUID] = mapped_column(ForeignKey("org_units.id"), primary_key=True)


class Geometry(Base, TimestampMixin):
    __tablename__ = "geometries"
    __table_args__ = (
        Index(
            "uq_geometry_current",
            "org_unit_id",
            unique=True,
            sqlite_where=text("valid_to IS NULL"),
            postgresql_where=text("valid_to IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    org_unit_id: Mapped[UUID] = mapped_column(ForeignKey("org_units.id"), nullable=False)
    geojson: Mapped[dict | None] = mapped_column(
        JSON,
        comment=(
            "GeoJSON polygon or point. A PostGIS column can be added when the extension is enabled."
        ),
    )
    geometry_kind: Mapped[str] = mapped_column(String(20), default="polygon", nullable=False)
    source: Mapped[str | None] = mapped_column(String(200))
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)


class Programme(Base, TimestampMixin):
    __tablename__ = "programmes"
    __table_args__ = (UniqueConstraint("code"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    first_release: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sensitive: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        comment="When true, additional MPDSR-style event permissions apply.",
    )

    indicators: Mapped[list["Indicator"]] = relationship(back_populates="programme")


class Indicator(Base, TimestampMixin):
    __tablename__ = "indicators"
    __table_args__ = (UniqueConstraint("code"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    programme_id: Mapped[UUID] = mapped_column(ForeignKey("programmes.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    programme: Mapped[Programme] = relationship(back_populates="indicators")
    versions: Mapped[list["IndicatorVersion"]] = relationship(
        back_populates="indicator",
        foreign_keys="IndicatorVersion.indicator_id",
    )


class IndicatorVersion(Base, TimestampMixin):
    __tablename__ = "indicator_versions"
    __table_args__ = (
        UniqueConstraint("indicator_id", "formula_version"),
        Index(
            "uq_indicator_versions_current",
            "indicator_id",
            unique=True,
            sqlite_where=text("is_current = 1"),
            postgresql_where=text("is_current"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    indicator_id: Mapped[UUID] = mapped_column(ForeignKey("indicators.id"), nullable=False)
    formula_version: Mapped[str] = mapped_column(String(40), nullable=False)
    numerator_definition: Mapped[str] = mapped_column(Text, nullable=False)
    denominator_type: Mapped[str] = mapped_column(String(40), nullable=False)
    denominator_coefficient: Mapped[float | None] = mapped_column(Float)
    denominator_reference_indicator_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("indicators.id")
    )
    multiplier: Mapped[float] = mapped_column(Float, default=100, nullable=False)
    unit: Mapped[str] = mapped_column(String(80), nullable=False)
    display_precision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    direction: Mapped[str] = mapped_column(String(40), nullable=False)
    target: Mapped[str | None] = mapped_column(String(80))
    green_band: Mapped[str | None] = mapped_column(String(120))
    yellow_band: Mapped[str | None] = mapped_column(String(120))
    red_band: Mapped[str | None] = mapped_column(String(120))
    blue_rule: Mapped[str | None] = mapped_column(Text)
    aggregation_method: Mapped[str] = mapped_column(
        String(40), default=AggregationMethod.SUM_THEN_CALCULATE.value, nullable=False
    )
    period_adjustment: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    methodology_text: Mapped[str | None] = mapped_column(Text)
    quality_rules: Mapped[dict | None] = mapped_column(JSON)
    formula_spec: Mapped[dict | None] = mapped_column(
        JSON, comment="Constrained formula AST. Never executable user code."
    )
    classification_spec: Mapped[dict | None] = mapped_column(JSON)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    indicator: Mapped[Indicator] = relationship(
        back_populates="versions",
        foreign_keys=[indicator_id],
    )
    denominator_reference_indicator: Mapped[Indicator | None] = relationship(
        foreign_keys=[denominator_reference_indicator_id],
    )


class IndicatorSourceMapping(Base, TimestampMixin):
    __tablename__ = "indicator_source_mappings"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    indicator_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("indicator_versions.id"), nullable=False
    )
    source_system: Mapped[str] = mapped_column(String(40), default=MappingSourceSystem.DHIS2.value)
    semantic_field: Mapped[str] = mapped_column(String(120), nullable=False)
    data_element_uid: Mapped[str | None] = mapped_column(
        String(80),
        comment="DHIS2 data-element/indicator UID. Configuration only; never business logic.",
    )
    category_option_combo_uid: Mapped[str | None] = mapped_column(String(80))
    program_uid: Mapped[str | None] = mapped_column(String(80))
    program_stage_uid: Mapped[str | None] = mapped_column(String(80))
    aggregation_behaviour: Mapped[str | None] = mapped_column(String(80))
    mapping_version: Mapped[str] = mapped_column(String(40), default="v1", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    item_kind: Mapped[str | None] = mapped_column(String(40))
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)


class PeriodPopulationRule(Base, TimestampMixin):
    """Configurable period → population-year resolution. Not buried in indicator code.

    ``financial_year_key`` holds the scope key: an FY key such as ``FY2025/26`` for
    financial-year rules, or a calendar year such as ``2025`` for calendar-year rules.
    A rule applies only to the period kinds listed in ``applies_to_period_kinds``;
    nothing is inferred for other period kinds.
    """

    __tablename__ = "period_population_rules"
    __table_args__ = (UniqueConstraint("financial_year_key", "programme_id"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    financial_year_key: Mapped[str] = mapped_column(String(20), nullable=False)
    population_year: Mapped[int] = mapped_column(Integer, nullable=False)
    programme_id: Mapped[UUID | None] = mapped_column(ForeignKey("programmes.id"))
    notes: Mapped[str | None] = mapped_column(Text)
    scope_kind: Mapped[str] = mapped_column(
        String(20), default=PeriodRuleScope.FINANCIAL_YEAR.value, nullable=False
    )
    applies_to_period_kinds: Mapped[list | None] = mapped_column(
        JSON, comment="Period kinds this rule governs, e.g. ['fy']. Other kinds stay unresolved."
    )
    approval_status: Mapped[str] = mapped_column(
        String(40), default=ApprovalStatus.DRAFT.value, nullable=False
    )


class PopulationVersion(Base, TimestampMixin):
    __tablename__ = "population_versions"
    __table_args__ = (UniqueConstraint("code"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_document: Mapped[str | None] = mapped_column(String(500))
    population_type: Mapped[str] = mapped_column(String(80), nullable=False)
    approval_status: Mapped[str] = mapped_column(
        String(40), default=ApprovalStatus.DRAFT.value, nullable=False
    )
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    imported_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    source_dataset: Mapped[str | None] = mapped_column(String(120))
    source_file_name: Mapped[str | None] = mapped_column(String(255))
    source_sha256: Mapped[str | None] = mapped_column(
        String(64), comment="Identity of the imported source file. A different checksum is a different source."
    )
    source_sheet: Mapped[str | None] = mapped_column(String(120))


class PopulationValue(Base, TimestampMixin):
    __tablename__ = "population_values"
    __table_args__ = (UniqueConstraint("version_id", "org_unit_id", "year"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    version_id: Mapped[UUID] = mapped_column(ForeignKey("population_versions.id"), nullable=False)
    org_unit_id: Mapped[UUID] = mapped_column(ForeignKey("org_units.id"), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    population: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    source_unit_name: Mapped[str | None] = mapped_column(String(255))
    source_unit_type: Mapped[str | None] = mapped_column(String(40))
    source_region: Mapped[str | None] = mapped_column(
        String(80), comment="Descriptive source metadata only. Never used as an organisational parent."
    )
    source_column_label: Mapped[str | None] = mapped_column(String(80))


class PopulationSourceAlias(Base, TimestampMixin):
    """Reviewed crosswalk between a source unit name and an internal organisation unit.

    Both names are preserved. Only approved entries may be used by an import.
    """

    __tablename__ = "population_source_aliases"
    __table_args__ = (UniqueConstraint("source_dataset", "source_unit_name"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    source_dataset: Mapped[str] = mapped_column(String(120), nullable=False)
    source_unit_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_unit_type: Mapped[str | None] = mapped_column(String(40))
    org_unit_id: Mapped[UUID | None] = mapped_column(ForeignKey("org_units.id"))
    target_name: Mapped[str | None] = mapped_column(
        String(255), comment="Internal or boundary name the source name was reviewed against."
    )
    decision_status: Mapped[str] = mapped_column(
        String(20), default=AliasDecisionStatus.PROPOSED.value, nullable=False
    )
    decision_note: Mapped[str | None] = mapped_column(Text)
    proposed_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    decided_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    evidence: Mapped[dict | None] = mapped_column(JSON)


class FacilityPopulationEntry(Base, TimestampMixin):
    __tablename__ = "facility_population_entries"
    __table_args__ = (
        Index(
            "uq_facility_current_approved",
            "org_unit_id",
            "year",
            unique=True,
            sqlite_where=text("is_current_approved = 1"),
            postgresql_where=text("is_current_approved"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    org_unit_id: Mapped[UUID] = mapped_column(ForeignKey("org_units.id"), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    population: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    source_name: Mapped[str] = mapped_column(String(255), nullable=False)
    population_type: Mapped[str] = mapped_column(String(80), nullable=False)
    approval_status: Mapped[str] = mapped_column(
        String(40), default=ApprovalStatus.DRAFT.value, nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    entered_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    approved_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    superseded_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("facility_population_entries.id")
    )
    is_current_approved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    rejection_reason: Mapped[str | None] = mapped_column(Text)


class SourceMapping(Base, TimestampMixin):
    """Administrator-managed aggregate source mappings. UIDs never enter calculation code."""

    __tablename__ = "source_mappings"
    __table_args__ = (UniqueConstraint("internal_source_key", "mapping_version", "programme_id"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    internal_source_key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    programme_id: Mapped[UUID] = mapped_column(ForeignKey("programmes.id"), nullable=False)
    dhis2_item_uid: Mapped[str | None] = mapped_column(
        String(80),
        comment="DHIS2 data-element or indicator UID. Test fixtures must use TEST_UID_* labels.",
    )
    item_kind: Mapped[str] = mapped_column(String(40), default="data_element", nullable=False)
    category_option_combo_uid: Mapped[str | None] = mapped_column(String(80))
    aggregation_semantics: Mapped[str | None] = mapped_column(String(80))
    mapping_version: Mapped[str] = mapped_column(String(40), default="v1", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)


class EventFieldMapping(Base, TimestampMixin):
    __tablename__ = "event_field_mappings"
    __table_args__ = (UniqueConstraint("internal_semantic_field", "mapping_version", "event_type"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    programme_id: Mapped[UUID | None] = mapped_column(ForeignKey("programmes.id"))
    program_uid: Mapped[str | None] = mapped_column(
        String(80), comment="DHIS2 program UID. Production values are not seeded."
    )
    program_stage_uid: Mapped[str | None] = mapped_column(String(80))
    source_data_element_uid: Mapped[str | None] = mapped_column(String(80))
    internal_semantic_field: Mapped[str] = mapped_column(String(120), nullable=False)
    expected_data_type: Mapped[str] = mapped_column(String(40), default="string", nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    mapping_version: Mapped[str] = mapped_column(String(40), default="v1", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)


class SyncJob(Base, TimestampMixin):
    __tablename__ = "sync_jobs"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    job_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), default=JobStatus.QUEUED.value, nullable=False)
    org_unit_id: Mapped[UUID | None] = mapped_column(ForeignKey("org_units.id"))
    programme_id: Mapped[UUID | None] = mapped_column(ForeignKey("programmes.id"))
    period_from: Mapped[str | None] = mapped_column(String(40))
    period_to: Mapped[str | None] = mapped_column(String(40))
    mapping_version: Mapped[str | None] = mapped_column(String(40))
    requested_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    received_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    stored_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rejected_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    flagged_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
    source_freshness_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    initiated_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    cancelled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str | None] = mapped_column(String(80))
    page_limit_reached: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    window_start: Mapped[date | None] = mapped_column(
        Date, comment="First event date actually requested from the source (inclusive)."
    )
    window_end: Mapped[date | None] = mapped_column(
        Date, comment="Last event date actually requested from the source (inclusive)."
    )


class RawAggregateValue(Base, TimestampMixin):
    __tablename__ = "raw_aggregate_values"
    __table_args__ = (
        Index(
            "uq_raw_aggregate_current",
            "source_system",
            "programme_id",
            "org_unit_id",
            "period",
            "internal_source_key",
            "category_option_combo_uid",
            unique=True,
            sqlite_where=text("is_current = 1"),
            postgresql_where=text("is_current"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    source_system: Mapped[str] = mapped_column(String(40), nullable=False)
    programme_id: Mapped[UUID | None] = mapped_column(ForeignKey("programmes.id"), index=True)
    org_unit_id: Mapped[UUID] = mapped_column(ForeignKey("org_units.id"), nullable=False)
    period: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    source_metric_id: Mapped[str] = mapped_column(String(120), nullable=False)
    internal_source_key: Mapped[str | None] = mapped_column(String(120), index=True)
    dhis2_org_unit_uid: Mapped[str | None] = mapped_column(String(80))
    dhis2_item_uid: Mapped[str | None] = mapped_column(String(80))
    category_option_combo_uid: Mapped[str | None] = mapped_column(String(80))
    value: Mapped[float | None] = mapped_column(Numeric(20, 6))
    extracted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_freshness_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_version: Mapped[str | None] = mapped_column(String(80))
    mapping_version: Mapped[str | None] = mapped_column(String(40))
    sync_job_id: Mapped[UUID | None] = mapped_column(ForeignKey("sync_jobs.id"))
    absence_reason: Mapped[str | None] = mapped_column(String(40))
    checksum: Mapped[str | None] = mapped_column(String(128))
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    superseded_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("raw_aggregate_values.id"))
    provenance: Mapped[dict | None] = mapped_column(JSON)
    value_invalid: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class RawEventSnapshot(Base, TimestampMixin):
    __tablename__ = "raw_event_snapshots"
    __table_args__ = (
        Index(
            "uq_raw_event_current",
            "event_uid",
            "source_connector",
            unique=True,
            sqlite_where=text("is_current = 1"),
            postgresql_where=text("is_current"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    event_uid: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
        comment="Source event UID. Presentation layers must not expose this to unprivileged users.",
    )
    programme_id: Mapped[UUID | None] = mapped_column(ForeignKey("programmes.id"), index=True)
    source_connector: Mapped[str] = mapped_column(String(40), default="tracker", nullable=False)
    program_uid: Mapped[str | None] = mapped_column(String(80))
    program_stage_uid: Mapped[str | None] = mapped_column(String(80))
    org_unit_id: Mapped[UUID] = mapped_column(ForeignKey("org_units.id"), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default=EventStatus.ACTIVE.value, nullable=False
    )
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    death_date: Mapped[date | None] = mapped_column(Date)
    notification_date: Mapped[date | None] = mapped_column(Date)
    review_date: Mapped[date | None] = mapped_column(Date)
    data_values: Mapped[dict | None] = mapped_column(
        JSON,
        comment=(
            "Approved semantic event fields only. Do not store names, narratives, "
            "or clinician identifiers by default."
        ),
    )
    extracted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    mapping_version: Mapped[str | None] = mapped_column(String(40))
    sync_job_id: Mapped[UUID | None] = mapped_column(ForeignKey("sync_jobs.id"))
    snapshot_hash: Mapped[str | None] = mapped_column(String(128))
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    superseded_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("raw_event_snapshots.id"))
    privacy_class: Mapped[str] = mapped_column(
        String(40), default=PrivacyClass.RESTRICTED_EVENT.value, nullable=False
    )


class CalculationRun(Base, TimestampMixin):
    __tablename__ = "calculation_runs"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    geography_org_unit_id: Mapped[UUID | None] = mapped_column(ForeignKey("org_units.id"))
    period: Mapped[str] = mapped_column(String(40), nullable=False)
    programme_id: Mapped[UUID | None] = mapped_column(ForeignKey("programmes.id"))
    population_version_id: Mapped[UUID | None] = mapped_column(ForeignKey("population_versions.id"))
    indicator_set_version: Mapped[str | None] = mapped_column(String(80))
    source_extracted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mapping_version: Mapped[str | None] = mapped_column(String(80))
    initiated_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default=JobStatus.QUEUED.value, nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    quality_flag_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    config_snapshot: Mapped[dict | None] = mapped_column(JSON)
    sync_job_id: Mapped[UUID | None] = mapped_column(ForeignKey("sync_jobs.id"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(80))
    software_version: Mapped[str | None] = mapped_column(String(40))
    aggregation_policy: Mapped[str | None] = mapped_column(String(80))
    evidence_manifest: Mapped[dict | None] = mapped_column(JSON)
    # Input fingerprint for run reuse (see calculation.RUN_REUSE_PREFIX); indexed by 0014.
    idempotency_key: Mapped[str | None] = mapped_column(String(80), index=True)


class CalculatedValue(Base, TimestampMixin):
    __tablename__ = "calculated_values"
    __table_args__ = (
        UniqueConstraint("calculation_run_id", "indicator_version_id", "org_unit_id", "period"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    calculation_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("calculation_runs.id"), nullable=False
    )
    indicator_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("indicator_versions.id"), nullable=False
    )
    org_unit_id: Mapped[UUID] = mapped_column(ForeignKey("org_units.id"), nullable=False)
    period: Mapped[str] = mapped_column(String(40), nullable=False)
    numerator: Mapped[float | None] = mapped_column(Numeric(20, 6))
    denominator: Mapped[float | None] = mapped_column(Numeric(20, 6))
    raw_value: Mapped[float | None] = mapped_column(Numeric(20, 8))
    display_value: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str | None] = mapped_column(String(20))
    performance_status: Mapped[str | None] = mapped_column(String(20))
    quality_status: Mapped[str | None] = mapped_column(String(20))
    unit: Mapped[str | None] = mapped_column(String(80))
    direction: Mapped[str | None] = mapped_column(String(40))
    target: Mapped[str | None] = mapped_column(String(80))
    display_precision: Mapped[int | None] = mapped_column(Integer)
    population_year: Mapped[int | None] = mapped_column(Integer)
    mapping_version: Mapped[str | None] = mapped_column(String(40))
    source_freshness_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    methodology_ref: Mapped[str | None] = mapped_column(String(120))
    blue_reason: Mapped[str | None] = mapped_column(Text)
    quality_flag_ids: Mapped[list | None] = mapped_column(JSON)
    population_version_id: Mapped[UUID | None] = mapped_column(ForeignKey("population_versions.id"))
    facility_population_entry_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("facility_population_entries.id")
    )
    aggregation_policy: Mapped[str | None] = mapped_column(String(80))
    aggregation_level: Mapped[str | None] = mapped_column(String(40))
    source_row_ids: Mapped[list | None] = mapped_column(JSON)
    source_mapping_ids: Mapped[list | None] = mapped_column(JSON)
    # How the population-derived target denominator was resolved (period kind, parent FY,
    # population year, fraction, coefficient, annual and adjusted target, population source).
    denominator_provenance: Mapped[dict | None] = mapped_column(JSON)
    software_version: Mapped[str | None] = mapped_column(String(40))
    missing_components: Mapped[list | None] = mapped_column(JSON)
    reason_code: Mapped[str | None] = mapped_column(
        String(80), comment="Machine-readable unavailable/unverified reason (UnavailableReason)."
    )
    event_snapshot_ids: Mapped[list | None] = mapped_column(
        JSON, comment="Event cohort rows used by this value. Never exposed to unprivileged users."
    )
    event_coverage: Mapped[dict | None] = mapped_column(JSON)


class QualityRule(Base, TimestampMixin):
    __tablename__ = "quality_rules"
    __table_args__ = (UniqueConstraint("code", "rule_version"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    rule_version: Mapped[str] = mapped_column(String(40), default="v1", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    config: Mapped[dict | None] = mapped_column(JSON)


class DataQualityFlag(Base, TimestampMixin):
    __tablename__ = "data_quality_flags"
    __table_args__ = (
        Index("ix_dq_flags_fingerprint", "fingerprint"),
        Index("ix_dq_flags_org_period", "org_unit_id", "period"),
        Index(
            "uq_dq_flag_open_fingerprint",
            "fingerprint",
            unique=True,
            sqlite_where=text("status IN ('open', 'acknowledged')"),
            postgresql_where=text("status IN ('open', 'acknowledged')"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    fingerprint: Mapped[str | None] = mapped_column(String(128))
    rule_id: Mapped[str] = mapped_column(String(80), nullable=False)
    rule_version: Mapped[str | None] = mapped_column(String(40))
    category: Mapped[str | None] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(20), default=QualitySeverity.WARNING.value)
    status: Mapped[str] = mapped_column(String(20), default=QualityStatus.OPEN.value)
    org_unit_id: Mapped[UUID | None] = mapped_column(ForeignKey("org_units.id"))
    programme_id: Mapped[UUID | None] = mapped_column(ForeignKey("programmes.id"))
    indicator_id: Mapped[UUID | None] = mapped_column(ForeignKey("indicators.id"))
    period: Mapped[str | None] = mapped_column(String(40))
    source_key: Mapped[str | None] = mapped_column(String(120))
    event_uid: Mapped[str | None] = mapped_column(
        String(80),
        comment="Protected source identifier. Do not expose through ordinary APIs.",
    )
    evidence: Mapped[dict | None] = mapped_column(JSON)
    explanation: Mapped[str | None] = mapped_column(Text)
    calculation_run_id: Mapped[UUID | None] = mapped_column(ForeignKey("calculation_runs.id"))
    sync_job_id: Mapped[UUID | None] = mapped_column(ForeignKey("sync_jobs.id"))
    resolution_note: Mapped[str | None] = mapped_column(Text)
    resolved_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    reopen_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class AnalysisSnapshot(Base, TimestampMixin):
    """One committed analytical screen state. Clients must reuse this identifier."""

    __tablename__ = "analysis_snapshots"
    __table_args__ = (
        Index(
            "uq_analysis_snapshots_user_request",
            "user_id",
            "idempotency_key",
            unique=True,
            sqlite_where=text("idempotency_key IS NOT NULL"),
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    idempotency_key: Mapped[str | None] = mapped_column(
        String(80), comment="Client request key. A repeated submission returns the committed snapshot."
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    org_unit_id: Mapped[UUID] = mapped_column(ForeignKey("org_units.id"), nullable=False)
    period: Mapped[str] = mapped_column(String(40), nullable=False)
    comparison_period: Mapped[str | None] = mapped_column(String(40))
    module: Mapped[str] = mapped_column(String(40), nullable=False)
    selected_indicator: Mapped[str | None] = mapped_column(String(80))
    view_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    current_run_id: Mapped[UUID | None] = mapped_column(ForeignKey("calculation_runs.id"))
    status: Mapped[str] = mapped_column(String(20), default=JobStatus.SUCCEEDED.value, nullable=False)
    software_version: Mapped[str | None] = mapped_column(String(40))
    payload_json: Mapped[dict | None] = mapped_column(JSON)
    evidence_json: Mapped[dict | None] = mapped_column(JSON)
    view_config: Mapped[dict | None] = mapped_column(JSON)


class SavedView(Base, TimestampMixin):
    __tablename__ = "saved_views"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    geography_org_unit_id: Mapped[UUID | None] = mapped_column(ForeignKey("org_units.id"))
    programme_id: Mapped[UUID | None] = mapped_column(ForeignKey("programmes.id"))
    period_rule: Mapped[str | None] = mapped_column(String(80))
    comparison_period: Mapped[str | None] = mapped_column(String(80))
    configuration: Mapped[dict | None] = mapped_column(JSON)


class ExportJob(Base, TimestampMixin):
    """Snapshot-bound export job.

    ``idempotency_key`` identifies user + snapshot + export type. ``active_key`` holds the
    same value while the job is live (queued, running, succeeded, or failed with a retry
    still permitted), so at most one live job — and one artifact — exists per key. A
    permanently failed job releases ``active_key`` but stays visible in history.
    """

    __tablename__ = "export_jobs"
    __table_args__ = (Index("uq_export_jobs_active_key", "active_key", unique=True),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    export_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default=JobStatus.QUEUED.value, nullable=False)
    org_unit_id: Mapped[UUID | None] = mapped_column(ForeignKey("org_units.id"))
    programme_id: Mapped[UUID | None] = mapped_column(ForeignKey("programmes.id"))
    period: Mapped[str | None] = mapped_column(String(40))
    calculation_run_id: Mapped[UUID | None] = mapped_column(ForeignKey("calculation_runs.id"))
    template_version: Mapped[str | None] = mapped_column(String(80))
    error_code: Mapped[str | None] = mapped_column(String(80))
    file_path: Mapped[str | None] = mapped_column(String(500))
    module: Mapped[str | None] = mapped_column(String(40))
    comparison_period: Mapped[str | None] = mapped_column(String(40))
    metadata_json: Mapped[dict | None] = mapped_column(JSON)
    analysis_snapshot_id: Mapped[UUID | None] = mapped_column(ForeignKey("analysis_snapshots.id"), index=True)
    view_hash: Mapped[str | None] = mapped_column(String(64))
    checksum: Mapped[str | None] = mapped_column(String(128))
    idempotency_key: Mapped[str | None] = mapped_column(String(200))
    active_key: Mapped[str | None] = mapped_column(String(200))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    max_attempts: Mapped[int | None] = mapped_column(Integer)
    dispatch_state: Mapped[str | None] = mapped_column(String(20))
    celery_task_id: Mapped[str | None] = mapped_column(String(155))
    claim_token: Mapped[str | None] = mapped_column(String(64))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Where the finished file lives, and when the bytes expire. Job metadata (including the
    # checksum) outlives the artifact, so an expired download is explainable rather than a 404.
    artifact_storage: Mapped[str | None] = mapped_column(String(20))
    artifact_media_type: Mapped[str | None] = mapped_column(String(120))
    artifact_size_bytes: Mapped[int | None] = mapped_column(Integer)
    artifact_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    artifact_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retry_scheduled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false(), nullable=False)


class AiRequest(Base, TimestampMixin):
    __tablename__ = "ai_requests"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    task: Mapped[str] = mapped_column(String(80), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(80))
    model: Mapped[str | None] = mapped_column(String(120))
    evidence_hash: Mapped[str | None] = mapped_column(String(128))
    calculation_run_id: Mapped[UUID | None] = mapped_column(ForeignKey("calculation_runs.id"))
    sensitivity_class: Mapped[str] = mapped_column(
        String(40), default=PrivacyClass.PUBLIC_AGGREGATE.value, nullable=False
    )
    token_usage: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default=JobStatus.QUEUED.value, nullable=False)
    prompt_version: Mapped[str | None] = mapped_column(String(40))
    fallback_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(80))
    response_json: Mapped[dict | None] = mapped_column(JSON)
    analysis_snapshot_id: Mapped[UUID | None] = mapped_column(ForeignKey("analysis_snapshots.id"), index=True)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(80))
    before_json: Mapped[dict | None] = mapped_column(JSON)
    after_json: Mapped[dict | None] = mapped_column(JSON)
    reason: Mapped[str | None] = mapped_column(Text)
    ip_address: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class FreshnessSnapshot(Base, TimestampMixin):
    __tablename__ = "freshness_snapshots"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    connector: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_freshness_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lag_seconds: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(40), default="unknown", nullable=False)
    sync_job_id: Mapped[UUID | None] = mapped_column(ForeignKey("sync_jobs.id"))
    detail: Mapped[dict | None] = mapped_column(JSON)


class OperationalEvent(Base):
    """Structured operational visibility. Payloads must never include secrets or MPDSR line lists."""

    __tablename__ = "operational_events"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    job_id: Mapped[str | None] = mapped_column(String(80))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    retry_count: Mapped[int | None] = mapped_column(Integer)
    records_received: Mapped[int | None] = mapped_column(Integer)
    records_stored: Mapped[int | None] = mapped_column(Integer)
    records_rejected: Mapped[int | None] = mapped_column(Integer)
    payload: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ExportArtifact(Base, TimestampMixin):
    """Export bytes for deployments where the API and worker have no shared filesystem.

    Small, aggregated export files only, bounded by EXPORT_ARTIFACT_MAX_BYTES and purged with
    the 24-hour export-file policy. Never raw DHIS2 extracts and never an export archive.
    """

    __tablename__ = "export_artifacts"
    __table_args__ = (UniqueConstraint("export_job_id"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    export_job_id: Mapped[UUID] = mapped_column(ForeignKey("export_jobs.id"), nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    media_type: Mapped[str | None] = mapped_column(String(120))
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum: Mapped[str] = mapped_column(String(128), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class MaintenanceRun(Base):
    """Operational record of one purge/maintenance pass.

    Counts and codes only: never deleted row contents, event UIDs, patient details,
    narratives, file paths or credentials.
    """

    __tablename__ = "maintenance_runs"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    task_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    policy: Mapped[str] = mapped_column(String(40), nullable=False)
    entity: Mapped[str] = mapped_column(String(60), nullable=False)
    requested_cutoff: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    rows_examined: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    rows_deleted: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    files_examined: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    files_deleted: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    rows_skipped: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    batches: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false(), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_summary: Mapped[str | None] = mapped_column(String(500))
    software_version: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class MaintenanceLock(Base):
    """Provider-neutral lease so two purge processes never work the same policy at once."""

    __tablename__ = "maintenance_locks"

    name: Mapped[str] = mapped_column(String(80), primary_key=True)
    holder: Mapped[str] = mapped_column(String(64), nullable=False)
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PopulationImportBatch(Base, TimestampMixin):
    """One governed ingestion of an approved population source.

    Staging preserves every source row and its match state before any organisation-unit
    crosswalk is approved, so an approved workbook is never silently attached to uncertain
    organisation units. Nothing here becomes a denominator until it is applied and approved.
    """

    __tablename__ = "population_import_batches"
    __table_args__ = (
        Index(
            "uq_population_import_batches_identity",
            "source_sha256",
            "importer_version",
            "reference_fingerprint",
            unique=True,
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    source_dataset: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    source_file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_display_name: Mapped[str | None] = mapped_column(String(255))
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_type: Mapped[str] = mapped_column(String(60), nullable=False)
    source_sheet: Mapped[str | None] = mapped_column(String(120))
    importer_version: Mapped[str] = mapped_column(String(40), nullable=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    imported_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    year_min: Mapped[int | None] = mapped_column(Integer)
    year_max: Mapped[int | None] = mapped_column(Integer)
    unit_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    district_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    city_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    national_totals: Mapped[dict | None] = mapped_column(JSON)
    region_totals: Mapped[dict | None] = mapped_column(JSON)
    match_counts: Mapped[dict | None] = mapped_column(JSON)
    reference_scope: Mapped[str] = mapped_column(String(40), nullable=False)
    # SHA-256 of the organisation-unit hierarchy, approved aliases and hierarchy approval reference
    # the rows were matched against. Same source + importer + reference = the same governed batch.
    reference_fingerprint: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    review_status: Mapped[str] = mapped_column(String(20), nullable=False)
    reviewed_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)


class PopulationImportRow(Base, TimestampMixin):
    """One staged source value: unit, declared type, broad region, year and population."""

    __tablename__ = "population_import_rows"
    __table_args__ = (UniqueConstraint("batch_id", "row_number", "year"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    batch_id: Mapped[UUID] = mapped_column(ForeignKey("population_import_batches.id"), nullable=False, index=True)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_unit_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_unit_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_region: Mapped[str | None] = mapped_column(String(80))
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    population: Mapped[int] = mapped_column(Integer, nullable=False)
    source_column_label: Mapped[str | None] = mapped_column(String(80))
    match_state: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    candidate_org_unit_id: Mapped[UUID | None] = mapped_column(ForeignKey("org_units.id"))
    alias_id: Mapped[UUID | None] = mapped_column(ForeignKey("population_source_aliases.id"))
    review_state: Mapped[str] = mapped_column(String(20), nullable=False)
    validation_error: Mapped[str | None] = mapped_column(String(255))

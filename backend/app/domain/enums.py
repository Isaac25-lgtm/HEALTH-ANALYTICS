from enum import StrEnum


class OrgUnitLevel(StrEnum):
    COUNTRY = "country"
    REGION = "region"
    SUB_REGION = "sub_region"
    DISTRICT = "district"
    CITY = "city"
    SUB_COUNTY = "sub_county"
    FACILITY = "facility"


# Lower rank is a higher analytical landing level.
ORG_UNIT_LEVEL_RANK: dict[OrgUnitLevel, int] = {
    OrgUnitLevel.COUNTRY: 0,
    OrgUnitLevel.REGION: 1,
    OrgUnitLevel.SUB_REGION: 1,
    OrgUnitLevel.DISTRICT: 2,
    OrgUnitLevel.CITY: 2,
    OrgUnitLevel.SUB_COUNTY: 3,
    OrgUnitLevel.FACILITY: 4,
}


class AggregationClass(StrEnum):
    """Approved administrative aggregation depth.

    Units in one class are peers for aggregation (for example districts and cities).
    Identical level_type text is not required, and differing text is not proof of a
    different depth.
    """

    COUNTRY = "country"
    REGION_EQUIVALENT = "region_equivalent"
    DISTRICT_EQUIVALENT = "district_equivalent"
    SUB_COUNTY = "sub_county"
    FACILITY = "facility"


AGGREGATION_CLASS_BY_LEVEL: dict[str, AggregationClass] = {
    OrgUnitLevel.COUNTRY.value: AggregationClass.COUNTRY,
    OrgUnitLevel.REGION.value: AggregationClass.REGION_EQUIVALENT,
    OrgUnitLevel.SUB_REGION.value: AggregationClass.REGION_EQUIVALENT,
    OrgUnitLevel.DISTRICT.value: AggregationClass.DISTRICT_EQUIVALENT,
    OrgUnitLevel.CITY.value: AggregationClass.DISTRICT_EQUIVALENT,
    OrgUnitLevel.SUB_COUNTY.value: AggregationClass.SUB_COUNTY,
    OrgUnitLevel.FACILITY.value: AggregationClass.FACILITY,
}

AGGREGATION_CLASS_RANK: dict[AggregationClass, int] = {
    AggregationClass.COUNTRY: 0,
    AggregationClass.REGION_EQUIVALENT: 1,
    AggregationClass.DISTRICT_EQUIVALENT: 2,
    AggregationClass.SUB_COUNTY: 3,
    AggregationClass.FACILITY: 4,
}


def aggregation_class(level_type: str | None) -> AggregationClass | None:
    return AGGREGATION_CLASS_BY_LEVEL.get(level_type or "")


class UnavailableReason(StrEnum):
    """Machine-readable reasons a calculated value is unavailable or unverified."""

    FORMULA_MISSING = "formula_missing"
    MISSING_COMPONENT = "missing_component"
    POPULATION_RULE_MISSING = "population_rule_missing"
    POPULATION_UNAVAILABLE = "population_unavailable"
    DENOMINATOR_MISSING = "denominator_missing"
    DENOMINATOR_ZERO = "denominator_zero"
    AMBIGUOUS_SOURCE = "ambiguous_source"
    MIXED_LEVELS = "mixed_levels"
    INCOMPLETE_CHILDREN = "incomplete_children"
    INCOMPATIBLE_SCOPE = "incompatible_aggregation_scope"
    MIXED_MAPPING_VERSIONS = "mixed_mapping_versions"
    EVENT_COVERAGE_UNVERIFIED = "event_coverage_unverified"


class EventCoverageStatus(StrEnum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"


class ChangeInterpretation(StrEnum):
    IMPROVED = "improved"
    DETERIORATED = "deteriorated"
    UNCHANGED = "unchanged"
    NOT_INTERPRETED = "not_interpreted"


class PeriodRuleScope(StrEnum):
    FINANCIAL_YEAR = "financial_year"
    CALENDAR_YEAR = "calendar_year"


class AliasDecisionStatus(StrEnum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"


class ActionPermission(StrEnum):
    VIEW = "view"
    EXPORT = "export"
    GENERATE_AI_REPORT = "generate_ai_report"
    EDIT_POPULATION = "edit_population"
    APPROVE_POPULATION = "approve_population"
    MANAGE_USERS = "manage_users"
    MANAGE_INDICATORS = "manage_indicators"
    MANAGE_MAPPINGS = "manage_mappings"
    MANAGE_SYNC = "manage_sync"
    ADMINISTER_AI = "administer_ai"
    VIEW_MPDSR_EVENTS = "view_mpdsr_events"
    EXPORT_MPDSR_LINELIST = "export_mpdsr_linelist"
    MANAGE_QUALITY = "manage_quality"


class ProgrammeCode(StrEnum):
    MNCH = "MNCH"
    EPI = "EPI"
    MPDSR = "MPDSR"


class IndicatorDirection(StrEnum):
    HIGHER_IS_BETTER = "higher_is_better"
    LOWER_IS_BETTER = "lower_is_better"
    DESIRED_RANGE = "desired_range"
    NEUTRAL_COUNT = "neutral_count"


class DenominatorType(StrEnum):
    POPULATION_DERIVED = "population_derived"
    SERVICE_DERIVED = "service_derived"
    EVENT_DERIVED = "event_derived"
    COMPOSITE = "composite"
    DIRECT_PERCENTAGE = "direct_percentage"
    COUNT = "count"


class AggregationMethod(StrEnum):
    SUM_THEN_CALCULATE = "sum_then_calculate"
    DIRECT_SOURCE = "direct_source"
    DIRECT_ONLY = "direct_only"
    EXPLICIT_AVERAGE = "explicit_average"


class PopulationType(StrEnum):
    CENSUS = "census"
    PROJECTION = "projection"
    APPROVED_LOCAL_ESTIMATE = "approved_local_estimate"
    FACILITY_CATCHMENT_ESTIMATE = "facility_catchment_estimate"
    FACILITY_CATCHMENT_OFFICIAL = "facility_catchment_official"


class ApprovalStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"


class PrivacyClass(StrEnum):
    PUBLIC_AGGREGATE = "public_aggregate"
    RESTRICTED_EVENT = "restricted_event"
    SENSITIVE_MATERNAL = "sensitive_maternal"


class EventStatus(StrEnum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    OTHER = "OTHER"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIALLY_SUCCEEDED = "partially_succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class QualitySeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    BLOCKING = "BLOCKING"


class QualityStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    SUPPRESSED = "suppressed"


class MappingSourceSystem(StrEnum):
    DHIS2 = "dhis2"
    SPREADSHEET = "spreadsheet"
    APPROVED_EXTERNAL = "approved_external"


class ConnectorType(StrEnum):
    AGGREGATE = "aggregate"
    EVENT_ANALYTICS_QUERY = "event_analytics_query"
    EVENT_ANALYTICS_AGGREGATE = "event_analytics_aggregate"
    TRACKER = "tracker"


class AbsenceReason(StrEnum):
    REPORTED_ZERO = "reported_zero"
    NO_SOURCE_ROW = "no_source_row"
    UNAVAILABLE = "unavailable"
    MAPPING_FAILURE = "mapping_failure"
    STALE = "stale"
    INVALID_VALUE = "invalid_value"


class Over100Behaviour(StrEnum):
    RETAIN_PERFORMANCE = "retain_performance"
    NON_ASSESSABLE = "non_assessable"
    FLAG_ONLY = "flag_only"


class FormulaKind(StrEnum):
    RATIO = "ratio"
    COUNT = "count"
    DIRECT_PERCENTAGE = "direct_percentage"
    DROPOUT = "dropout"


class Dhis2AuthMethod(StrEnum):
    BASIC = "basic"
    PAT = "pat"


class PopulationAggregationPolicy(StrEnum):
    DIRECT_OR_COMPLETE_CHILDREN = "direct_or_complete_children"
    DIRECT_IF_PRESENT = "direct_if_present"


class SourceAggregationPolicy(StrEnum):
    DIRECT_OR_COMPLETE_CHILDREN = "direct_or_complete_children"
    DIRECT_ONLY = "direct_only"


ACTIVE_NOT_COMPLETED_LABEL = "Active (not completed)"


class PerformanceStatus(StrEnum):
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"
    BLUE = "blue"
    NA = "n_a"

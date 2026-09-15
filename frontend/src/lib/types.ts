export type OrgUnitSummary = {
  id: string;
  code: string;
  name: string;
  level_type: string;
  parent_id: string | null;
  path: string;
  ownership?: string | null;
  facility_level?: string | null;
};

export type CurrentContext = {
  user_id: string;
  username: string;
  display_name: string;
  role_codes: string[];
  landing_org_unit: OrgUnitSummary | null;
  landing_org_units: OrgUnitSummary[];
  geography_scopes: OrgUnitSummary[];
  programmes: string[];
  actions: string[];
  identity_provider: string;
};

export type Measure = {
  indicator_code?: string | null;
  name?: string | null;
  raw_value: number | null;
  display_value: string | null;
  numerator: number | null;
  denominator: number | null;
  unit: string | null;
  status: string;
  performance_status?: string | null;
  quality_status?: string | null;
  blue_reason?: string | null;
  missing_components?: string[] | null;
  aggregation_policy?: string | null;
  mapping_version?: string | null;
  population_year?: number | null;
  population_version_id?: string | null;
  facility_population_entry_id?: string | null;
  formula_version?: string | null;
  calculation_run_id?: string | null;
  denominator_type?: string | null;
  direction?: string | null;
  classification_mode?: string | null;
  desired_range?: number[] | null;
  display_precision?: number | null;
  reason_code?: string | null;
  aggregation_level?: string | null;
  source_freshness_at?: string | null;
  event_coverage_status?: string | null;
  thresholds?: { state: string; text: string } | null;
  population_derived?: boolean;
  comparison?: Measure;
  change?: MeasureChange;
};

export type ChangeInterpretation = "improved" | "deteriorated" | "unchanged" | "not_interpreted";

export type MeasureChange = {
  absolute_change: number | null;
  percentage_point_change: number | null;
  relative_percent_change: number | null;
  change_kind: string | null;
  interpretation?: ChangeInterpretation | null;
  interpretation_reason?: string | null;
  status_transition?: Array<string | null> | null;
};

export type MapState = "mapped" | "geometry_unavailable_for_level" | "mixed_levels_not_mapped" | "no_map_units" | "not_available";

export type MapBlock = {
  map_state: MapState;
  mapping_note: string | null;
  map_level: string | null;
  map_level_types: string[];
  map_parent_org_unit_id: string;
  map_feature_org_unit_ids: string[];
  selected_indicator: string | null;
  map_value_run_ids: Record<string, string | null>;
  geometry_effective_date: string;
  missing_geometry_ids: string[];
  missing_value_ids: string[];
};

export type MapFeatureCollection = {
  type: "FeatureCollection";
  map_state: MapState;
  mapping_note: string | null;
  map_level: string | null;
  selected_indicator: string | null;
  geometry_effective_date: string | null;
  feature_count: number;
  missing_geometry_ids: string[];
  missing_value_ids: string[];
  features: Array<{
    type: "Feature";
    id: string;
    properties: {
      org_unit_id: string;
      code: string;
      name: string;
      level_type: string;
      parent_id: string | null;
      indicator_code: string | null;
      raw_value: number | null;
      display_value: string | null;
      unit: string | null;
      status: string | null;
      quality_status: string | null;
      calculation_run_id: string | null;
    };
    geometry: {
      type: string;
      coordinates: unknown;
    } | null;
  }>;
};

export type RankingEntry = {
  org_unit_id: string;
  org_unit_code?: string | null;
  org_unit_name?: string | null;
  level_type?: string | null;
  raw_value: number | null;
  display_value: string | null;
  unit?: string | null;
  status?: string | null;
};

export type Ranking = {
  indicator_code: string;
  classification_mode: string;
  direction?: string | null;
  ranking_allowed: boolean;
  order_rule: string | null;
  reason: string | null;
  reason_code: string | null;
  best: RankingEntry[];
  worst: RankingEntry[];
  ordered_org_unit_ids: string[];
  excluded: { blue: RankingEntry[]; missing: RankingEntry[]; non_assessable: RankingEntry[] };
};

export type CauseDisclosure = {
  status: "disclosed" | "withheld";
  reason?: string;
  level?: string;
  min_cell_count?: number;
  suppressed_categories?: number;
};

export type MpdsrExtras = {
  structured_cause_mentions: Array<{ code?: string; category: string; mentions: number }>;
  cause_note?: string;
  cause_disclosure?: CauseDisclosure;
  active_events: { label?: string; count?: number } | null;
};

export type DashboardResponse = {
  screen: "national" | "regional" | "district" | "sub_county" | "facility";
  scope: OrgUnitSummary & {
    district: OrgUnitSummary | null;
    sub_county: OrgUnitSummary | null;
  };
  ancestors: OrgUnitSummary[];
  period: string;
  comparison_period: string;
  module: string;
  available_modules: string[];
  programmes: string[];
  actions: string[];
  can_edit_population: boolean;
  population: {
    status: string;
    population: number | null;
    year: number | null;
    source: string | null;
    version_code: string | null;
    approval_status: string | null;
    population_type: string | null;
    reason: string | null;
    official_or_estimated: string | null;
  };
  kpis: Measure[];
  module_result: {
    indicators: Measure[];
    trends: Array<{
      period: string;
      calculation_run_id: string;
      values: Record<string, Measure>;
    }>;
    org_unit_comparison: Array<{
      org_unit_id: string;
      org_unit_code: string;
      org_unit_name: string;
      level_type: string;
      ownership?: string | null;
      facility_level?: string | null;
      values: Record<string, Measure>;
    }>;
    freshness: {
      raw_row_count: number;
      latest_extracted_at: string | null;
      latest_source_freshness_at?: string | null;
      availability: string;
    };
    quality_flags: Array<{
      id: string;
      rule_id: string;
      severity: string;
      explanation: string;
    }>;
    current_run_id: string;
    comparison_run_id?: string;
    comparison_grain?: string;
    continuum?: Record<string, unknown> | null;
    mpdsr?: MpdsrExtras | null;
  };
  facility_scorecard: Array<{
    org_unit_id: string;
    org_unit_code: string;
    org_unit_name: string;
    ownership?: string | null;
    facility_level?: string | null;
    values: Record<string, Measure>;
  }>;
  ranking: Ranking;
  selected_indicator: string;
  insights: Array<{
    severity: string;
    code: string;
    title: string;
    detail: string;
    indicator_code?: string;
  }>;
  analysis_snapshot_id: string;
  view_hash: string;
  request_key: string | null;
  snapshot_reused?: boolean;
  snapshot_created_at?: string | null;
  map: MapBlock;
  exports: {
    phase6_implemented: boolean;
    actions: Array<{
      kind: string;
      label: string;
      format: string;
      available: boolean;
      implemented: boolean;
      message: string;
    }>;
  };
};

export type DashboardQuery = {
  orgUnitId: string;
  period: string;
  module?: string;
  comparison?: string;
  indicator?: string;
  requestKey: string;
};

export type AiFinding = {
  title: string;
  detail: string;
  indicator_code?: string | null;
  evidence_run_id?: string | null;
};

export type AiResponse = {
  ai_request_id: string;
  task: string;
  mode: string;
  fallback_used: boolean;
  prompt_version: string;
  evidence_hash: string;
  calculation_run_id: string | null;
  result: {
    text?: string;
    unsupported?: boolean;
    findings?: AiFinding[];
    mode?: string;
  };
};

export type ExportJobSummary = {
  job_id: string;
  status: string;
  export_type: string;
  label: string;
  period: string | null;
  module: string | null;
  analysis_snapshot_id: string | null;
  downloadable: boolean;
  artifact_expired: boolean;
  artifact_expires_at: string | null;
  error_code: string | null;
  error_message: string | null;
  retryable: boolean;
  retry_scheduled: boolean;
  permanent_failure: boolean;
  attempt_count: number;
  max_attempts: number | null;
  created_at: string | null;
  finished_at: string | null;
};

import type { CurrentContext, DashboardResponse, Measure } from "@/lib/types";

/**
 * Synthetic structural fixture for component tests. Values are arbitrary test numbers, not
 * official or prototype data, and exist only to exercise layout and missing-value states.
 */
export function measure(code: string, overrides: Partial<Measure> = {}): Measure {
  return {
    indicator_code: code,
    name: `${code} name`,
    raw_value: 41.5,
    display_value: "41.5",
    numerator: 83,
    denominator: 200,
    unit: "%",
    status: "yellow",
    ...overrides,
  };
}

export function fixtureContext(overrides: Partial<CurrentContext> = {}): CurrentContext {
  return {
    user_id: "user-1",
    username: "fixture.user",
    display_name: "Fixture User",
    role_codes: ["regional_analyst"],
    landing_org_unit: null,
    landing_org_units: [],
    geography_scopes: [],
    geography_entry_units: [],
    available_geography_levels: [],
    programmes: ["MNCH", "EPI"],
    actions: ["view", "export"],
    identity_provider: "local",
    ...overrides,
  };
}

export function fixtureDashboard(overrides: Partial<DashboardResponse> = {}): DashboardResponse {
  const kpis = [
    measure("KPI_A"),
    measure("KPI_B", { raw_value: null, display_value: null, status: "n_a", reason_code: "population_unavailable" }),
    measure("KPI_C", { status: "green" }),
    measure("KPI_D", { unit: "count", display_value: "12", raw_value: 12, status: "unclassified" }),
    measure("KPI_E"),
    measure("KPI_F"),
    measure("KPI_G"),
  ];
  const unit = (id: string, name: string) => ({
    org_unit_id: id,
    org_unit_code: id.toUpperCase(),
    org_unit_name: name,
    level_type: "district",
    values: Object.fromEntries(kpis.map((row) => [row.indicator_code as string, row])),
  });
  return {
    screen: "regional",
    scope: {
      id: "scope-1",
      code: "SCOPE",
      name: "Fixture Region",
      level_type: "sub_region",
      parent_id: null,
      path: "/UG/SCOPE",
      district: null,
      sub_county: null,
    },
    ancestors: [],
    period: "FY2024/25",
    comparison_period: "FY2023/24",
    module: "anc",
    available_modules: ["anc", "mpdsr"],
    programmes: ["MNCH"],
    actions: ["view", "export"],
    can_edit_population: false,
    population: {
      status: "unavailable",
      population: null,
      year: 2024,
      source: null,
      version_code: null,
      approval_status: null,
      population_type: null,
      reason: "No approved population version covers this year and geography.",
      official_or_estimated: null,
    },
    kpis,
    module_result: {
      indicators: kpis,
      trends: [
        { period: "FY2022/23", calculation_run_id: "run-0", values: { KPI_A: measure("KPI_A", { raw_value: 30 }) } },
        { period: "FY2023/24", calculation_run_id: "run-1", values: { KPI_A: measure("KPI_A", { raw_value: null }) } },
        { period: "FY2024/25", calculation_run_id: "run-2", values: { KPI_A: measure("KPI_A") } },
      ],
      org_unit_comparison: [unit("u-1", "Fixture District One"), unit("u-2", "Fixture District Two")],
      freshness: { raw_row_count: 3, latest_extracted_at: null, availability: "available" },
      quality_flags: Array.from({ length: 12 }, (_, index) => ({
        id: `flag-${index}`,
        rule_id: "MISSING_DENOMINATOR",
        severity: index % 3 === 0 ? "blocking" : "warning",
        explanation: `Fixture flag ${index}`,
      })),
      current_run_id: "run-2",
      continuum: { note: "Continuum note", mv1_to_mv4: { raw_value: null, unit: "%", threshold_state: "no_approved_threshold" } },
      mpdsr: {
        structured_cause_mentions: [],
        cause_note: "Structured cause mentions only.",
        cause_disclosure: { status: "withheld", reason: "No approved MPDSR cause taxonomy is configured." },
        active_events: null,
      },
    },
    facility_scorecard: [
      {
        org_unit_id: "f-1",
        org_unit_code: "F1",
        org_unit_name: "Fixture Facility",
        facility_level: "HC III",
        values: Object.fromEntries(kpis.map((row) => [row.indicator_code as string, row])),
      },
    ],
    ranking: {
      indicator_code: "KPI_A",
      classification_mode: "higher_is_better",
      ranking_allowed: false,
      order_rule: null,
      reason: "Ranking needs an approved classification rule.",
      reason_code: "ranking_not_allowed",
      best: [],
      worst: [],
      ordered_org_unit_ids: [],
      excluded: { blue: [], missing: [], non_assessable: [] },
    },
    selected_indicator: "KPI_A",
    insights: Array.from({ length: 9 }, (_, index) => ({
      severity: index === 5 ? "high" : "medium",
      code: `INSIGHT_${index}`,
      title: `Fixture insight ${index}`,
      detail: "Detail",
    })),
    analysis_snapshot_id: "snapshot-0001-fixture",
    view_hash: "hash",
    request_key: "request-key",
    map: {
      map_state: "geometry_unavailable_for_level",
      mapping_note: null,
      map_level: null,
      map_level_types: [],
      map_parent_org_unit_id: "scope-1",
      map_feature_org_unit_ids: [],
      selected_indicator: "KPI_A",
      map_value_run_ids: {},
      geometry_effective_date: "not verified",
      missing_geometry_ids: [],
      missing_value_ids: [],
    },
    exports: {
      phase6_implemented: true,
      actions: [
        { kind: "excel", label: "Excel workbook (.xlsx)", format: "xlsx", available: true, implemented: true, message: "" },
        { kind: "pdf", label: "PDF report (.pdf)", format: "pdf", available: false, implemented: false, message: "Pending" },
      ],
    },
    ...overrides,
  };
}

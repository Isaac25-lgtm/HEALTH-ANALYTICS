"use client";

import { DEFAULT_COMPARISON, MODULE_LABELS, PERIOD_OPTIONS } from "@/lib/scope";
import type { CurrentContext, DashboardResponse, OrgUnitSummary } from "@/lib/types";

export type FilterChange = {
  orgUnitId: string;
  period: string;
  comparison: string;
  module: string;
  indicator: string;
};

const ROLE_LABELS: Record<string, string> = {
  national_analyst: "National Analyst",
  regional_analyst: "Regional Analyst",
  district_mch_focal: "District MCH Focal Person",
  facility_user: "Facility User",
  view_only: "View only",
  mpdsr_analyst: "MPDSR Analyst",
  system_administrator: "System Administrator",
};

export function roleLabel(context: CurrentContext): string {
  const code = context.role_codes[0];
  return code ? ROLE_LABELS[code] ?? code.replaceAll("_", " ") : "No role";
}

/**
 * One compact strip: scope and role, then period, comparison, geography, programme module and
 * indicator. Applying the strip starts a new analytical execution for the new request.
 */
export function FilterStrip({
  dashboard,
  context,
  geographyOptions,
  comparison,
  onApply,
}: {
  dashboard: DashboardResponse;
  context: CurrentContext;
  geographyOptions: OrgUnitSummary[];
  comparison?: string;
  onApply: (change: FilterChange) => void;
}) {
  const selectedCode = dashboard.selected_indicator ?? dashboard.ranking.indicator_code;
  return (
    <form
      className="filter-strip"
      aria-label="Scope and period"
      onSubmit={(event) => {
        event.preventDefault();
        const data = new FormData(event.currentTarget);
        onApply({
          orgUnitId: String(data.get("orgUnitId")),
          period: String(data.get("period")),
          comparison: String(data.get("comparison")),
          module: String(data.get("module")),
          indicator: String(data.get("indicator") || ""),
        });
      }}
    >
      <p className="filter-scope">
        <span className="filter-key">Scope</span> <strong>{dashboard.scope.name}</strong>
        <span className="filter-key filter-key-gap">Role</span> <strong>{roleLabel(context)}</strong>
      </p>
      <label>
        <span>Period</span>
        <select name="period" defaultValue={dashboard.period} aria-label="Period">
          {PERIOD_OPTIONS.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      </label>
      <label>
        <span>Compare</span>
        <select
          name="comparison"
          defaultValue={dashboard.comparison_period ?? comparison ?? DEFAULT_COMPARISON}
          aria-label="Comparison period"
        >
          {PERIOD_OPTIONS.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      </label>
      <label>
        <span>Geography</span>
        <select name="orgUnitId" defaultValue={dashboard.scope.id} aria-label="Geography">
          {geographyOptions.map((unit) => (
            <option key={unit.id} value={unit.id}>
              {unit.name} ({unit.level_type.replaceAll("_", " ")})
            </option>
          ))}
        </select>
      </label>
      <label>
        <span>Programme</span>
        <select name="module" defaultValue={dashboard.module} aria-label="Programme module">
          {dashboard.available_modules.map((code) => (
            <option key={code} value={code}>
              {MODULE_LABELS[code] ?? code}
            </option>
          ))}
        </select>
      </label>
      <label>
        <span>Indicator</span>
        <select name="indicator" defaultValue={selectedCode} aria-label="Selected indicator">
          {dashboard.module_result.indicators.map((row) => (
            <option key={row.indicator_code ?? row.name} value={row.indicator_code ?? ""}>
              {row.name ?? row.indicator_code}
            </option>
          ))}
        </select>
      </label>
      <button type="submit" className="primary-button">
        Apply
      </button>
    </form>
  );
}

/**
 * Data age, snapshot lineage and the population notice on one line. A missing population is
 * stated plainly; population-derived indicators then show as unavailable, never as zero.
 */
export function StatusLine({
  dashboard,
  kicker,
  onRecalculate,
}: {
  dashboard: DashboardResponse;
  kicker: string;
  onRecalculate: () => void;
}) {
  const freshness = dashboard.module_result.freshness;
  const population = dashboard.population;
  return (
    <div className="status-line">
      <p className="freshness">
        <strong className="kicker">{kicker}</strong>
        <span>
          {" "}
          · data: {freshness.availability.replaceAll("_", " ")}
          {freshness.latest_source_freshness_at ? ` · source ${freshness.latest_source_freshness_at}` : ""}
          {freshness.latest_extracted_at ? ` · extracted ${freshness.latest_extracted_at}` : ""}
        </span>
        <span title={`Run ${dashboard.module_result.current_run_id}`}> · snapshot {dashboard.analysis_snapshot_id}</span>{" "}
        <button type="button" className="link-button" onClick={onRecalculate}>
          Recalculate
        </button>
      </p>
      {population.status === "unavailable" ? (
        <p className="population-notice" role="status" title={population.reason ?? undefined}>
          Approved population is unavailable: population-derived indicators are non-assessable and missing population is
          not treated as zero.
          {dashboard.can_edit_population ? " A catchment entry can be drafted." : ""}
        </p>
      ) : (
        <p className="population-ok">
          Population {population.population?.toLocaleString()} · {population.year} ·{" "}
          {population.source ?? "source not stated"} · {population.approval_status ?? "n/a"}
        </p>
      )}
    </div>
  );
}

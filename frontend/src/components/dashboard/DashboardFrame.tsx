"use client";

import { DEFAULT_COMPARISON, MODULE_LABELS, PERIOD_OPTIONS } from "@/lib/scope";
import type { CurrentContext, DashboardResponse, OrgUnitSummary } from "@/lib/types";
import { Icon } from "../ui/Icon";
import { SearchBox } from "./SearchBox";

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
        const selectedModule = String(data.get("module"));
        // The indicator list belongs to the module currently on screen. Carrying one of its codes
        // into a different module asks the server for a pair it must reject, so a module change
        // falls back to that module's own default indicator.
        const indicator = selectedModule === dashboard.module ? String(data.get("indicator") || "") : "";
        onApply({
          orgUnitId: String(data.get("orgUnitId")),
          period: String(data.get("period")),
          comparison: String(data.get("comparison")),
          module: selectedModule,
          indicator,
        });
      }}
    >
      <p className="filter-scope">
        <span className="filter-chip">
          <Icon name="scope" size={18} />
          <span className="filter-key">Scope:</span> <strong>{dashboard.scope.name}</strong>
        </span>
        <span className="filter-chip">
          <Icon name="role" size={18} />
          <span className="filter-key">Role:</span> <strong>{roleLabel(context)}</strong>
        </span>
      </p>
      <label className="filter-field">
        <span>Period</span>
        <Icon name="calendar" size={16} className="field-icon" />
        <select name="period" defaultValue={dashboard.period} aria-label="Period">
          {PERIOD_OPTIONS.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      </label>
      <label className="filter-field">
        <span>Compare</span>
        <Icon name="compare" size={16} className="field-icon" />
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
      <label className="filter-field">
        <span>Geography</span>
        <Icon name="pin" size={16} className="field-icon" />
        <select name="orgUnitId" defaultValue={dashboard.scope.id} aria-label="Geography">
          {geographyOptions.map((unit) => (
            <option key={unit.id} value={unit.id}>
              {unit.name} ({unit.level_type.replaceAll("_", " ")})
            </option>
          ))}
        </select>
      </label>
      <label className="filter-field">
        <span>Programme</span>
        <Icon name="programme" size={16} className="field-icon" />
        <select name="module" defaultValue={dashboard.module} aria-label="Programme module">
          {dashboard.available_modules.map((code) => (
            <option key={code} value={code}>
              {MODULE_LABELS[code] ?? code}
            </option>
          ))}
        </select>
      </label>
      <label className="filter-field">
        <span>Indicator</span>
        <Icon name="indicator" size={16} className="field-icon" />
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
      <SearchBox period={dashboard.period} comparison={comparison} orgUnitId={dashboard.scope.id} />
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
          {freshness.latest_source_freshness_at ? (
            <span data-volatile> · source {freshness.latest_source_freshness_at}</span>
          ) : null}
          {freshness.latest_extracted_at ? <span data-volatile> · extracted {freshness.latest_extracted_at}</span> : null}
        </span>
        <span title={`Run ${dashboard.module_result.current_run_id}`}>
          {" "}
          · snapshot <span data-volatile>{dashboard.analysis_snapshot_id}</span>
        </span>{" "}
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

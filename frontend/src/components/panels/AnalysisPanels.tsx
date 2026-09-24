"use client";

import { useState } from "react";
import { periodLabel } from "@/lib/periods";
import { formatMeasure, resolveStatus, statusMeta } from "@/lib/status";
import type { DashboardResponse, Measure, RankingEntry } from "@/lib/types";
import { AdaptiveMap } from "../maps/AdaptiveMap";
import { TrendChart } from "../ui/TrendChart";
import { Panel } from "./Panel";

/** The indicator's display name from the snapshot, falling back to its code. */
function indicatorName(dashboard: DashboardResponse, code: string | null | undefined): string {
  if (!code) {
    return "Selected indicator";
  }
  const match = dashboard.module_result.indicators.find((row) => row.indicator_code === code);
  return match?.name ?? code;
}

export function MapPanel({
  dashboard,
  comparison,
  className,
}: {
  dashboard: DashboardResponse;
  comparison?: string;
  className?: string;
}) {
  const block = dashboard.map;
  return (
    <Panel
      icon="maps"
      title="Geographic intelligence"
      subtitle={`${indicatorName(dashboard, block.selected_indicator ?? dashboard.selected_indicator)} · ${periodLabel(dashboard.period)}`}
      className={className}
      bodyClassName="panel-body-map"
    >
      <AdaptiveMap dashboard={dashboard} period={dashboard.period} comparison={comparison} />
    </Panel>
  );
}

export function TrendPanel({
  dashboard,
  className,
  title = "Trends",
}: {
  dashboard: DashboardResponse;
  className?: string;
  title?: string;
}) {
  const indicators = dashboard.kpis.filter((row) => row.indicator_code);
  const [code, setCode] = useState<string>(dashboard.selected_indicator ?? indicators[0]?.indicator_code ?? "");
  const selected: Measure | undefined = indicators.find((row) => row.indicator_code === code);
  return (
    <Panel
      icon="trends"
      title={title}
      subtitle={selected?.name ?? code}
      className={className}
      actions={
        indicators.length > 1 ? (
          <select aria-label="Trend indicator" value={code} onChange={(event) => setCode(event.target.value)}>
            {indicators.map((row) => (
              <option key={row.indicator_code} value={row.indicator_code ?? ""}>
                {row.name ?? row.indicator_code}
              </option>
            ))}
          </select>
        ) : null
      }
    >
      <TrendChart trends={dashboard.module_result.trends} indicatorCode={code} />
    </Panel>
  );
}

const ORDER_RULE_LABELS: Record<string, string> = {
  higher_values_rank_first: "Higher values rank first for this indicator.",
  lower_values_rank_first: "Lower values rank first for this indicator.",
  closest_to_desired_range_ranks_first: "Values closest to the approved desired range rank first.",
};

/**
 * Horizontal bars for ranked units. Bar length is screen scaling of the server's value only
 * (percentages against 100%, or the largest value shown when above 100%); the fill is the
 * server's status colour.
 */
function RankingBars({ rows, tone }: { rows: RankingEntry[]; tone: "best" | "worst" }) {
  if (!rows.length) {
    return <p className="panel-empty">No ranked units.</p>;
  }
  const values = rows.map((row) => row.raw_value).filter((value): value is number => value != null);
  const percent = rows.some((row) => row.unit === "%");
  const scale = Math.max(percent ? 100 : 0, ...values, 0) || 1;
  // Bar length is a fraction of the widest bar, drawn with a CSS scale; no value is derived.
  return (
    <ol className={`rank-list rank-${tone}`}>
      {rows.map((row) => {
        const status = resolveStatus(row);
        const fraction = row.raw_value == null ? 0 : Math.max(0.02, Math.max(row.raw_value, 0) / scale);
        return (
          <li key={row.org_unit_id}>
            <span className="rank-name" title={row.org_unit_name ?? row.org_unit_code ?? undefined}>
              {row.org_unit_name ?? row.org_unit_code}
            </span>
            <span className="rank-bar" aria-hidden="true">
              <span className={`rank-fill fill-${status}`} style={{ transform: `scaleX(${fraction})` }} />
            </span>
            <span className="rank-value num">{formatMeasure(row.raw_value, row.unit ?? null, row.display_value)}</span>
            {/* The bar colour carries the status; the label is kept for screen readers. */}
            <span className="sr-only">{statusMeta(status).label}</span>
          </li>
        );
      })}
    </ol>
  );
}

/** Best and needs-attention units exactly as ranked by the server's approved ordering rule. */
export function RankingPanel({ dashboard, className }: { dashboard: DashboardResponse; className?: string }) {
  const ranking = dashboard.ranking;
  const excluded = ranking.excluded ?? { blue: [], missing: [], non_assessable: [] };
  const notRanked = excluded.blue.length + excluded.missing.length + excluded.non_assessable.length;
  return (
    <Panel
      icon="chart"
      title="Top and bottom performers"
      subtitle={`${indicatorName(dashboard, ranking.indicator_code)} · ${ranking.order_rule ? ORDER_RULE_LABELS[ranking.order_rule] ?? ranking.order_rule : "no approved ordering"}`}
      className={className}
      footer={
        notRanked ? (
          <span className="panel-note">
            Not ranked: {excluded.blue.length} non-assessable (BLUE), {excluded.missing.length} without a value,{" "}
            {excluded.non_assessable.length} without an approved status.
          </span>
        ) : undefined
      }
    >
      {ranking.ranking_allowed ? (
        <div className="rank-columns">
          <div>
            <h3 className="panel-subhead">Best performing</h3>
            <RankingBars rows={ranking.best} tone="best" />
          </div>
          <div>
            <h3 className="panel-subhead">Needs attention</h3>
            <RankingBars rows={ranking.worst} tone="worst" />
          </div>
        </div>
      ) : (
        <p className="panel-empty">{ranking.reason ?? "Ranking is not available for this indicator."}</p>
      )}
    </Panel>
  );
}

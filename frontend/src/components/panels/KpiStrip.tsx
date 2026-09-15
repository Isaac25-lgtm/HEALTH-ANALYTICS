import { KpiCard } from "../ui/KpiCard";
import type { DashboardResponse } from "@/lib/types";

export const KPI_STRIP_SIZE = 6;

/**
 * Six compact headline cards from the snapshot's KPI list, each with its own server-calculated
 * trend series. Further indicators remain in the scorecard; nothing is dropped from the data.
 */
export function KpiStrip({ dashboard, size = KPI_STRIP_SIZE }: { dashboard: DashboardResponse; size?: number }) {
  const kpis = dashboard.kpis.slice(0, size);
  if (!kpis.length) {
    return (
      <p className="kpi-strip-empty" role="status">
        No headline indicators are configured for this module and scope.
      </p>
    );
  }
  const trends = dashboard.module_result.trends;
  return (
    <section className="kpi-strip" aria-label="Key indicators">
      {kpis.map((measure) => (
        <KpiCard
          key={measure.indicator_code}
          measure={measure}
          comparisonPeriod={dashboard.comparison_period}
          series={trends.map((row) => row.values[measure.indicator_code ?? ""]?.raw_value ?? null)}
        />
      ))}
    </section>
  );
}

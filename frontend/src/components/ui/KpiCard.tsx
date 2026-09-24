import { periodLabel } from "@/lib/periods";
import { changeLabel, formatMeasure, interpretationLabel, resolveStatus, unavailableLabel } from "@/lib/status";
import type { Measure } from "@/lib/types";
import { Icon } from "./Icon";
import { Sparkline } from "./Sparkline";
import { StatusPill } from "./StatusPill";

export function KpiCard({
  measure,
  comparisonPeriod,
  series,
}: {
  measure: Measure;
  comparisonPeriod?: string | null;
  /** Server-calculated values for the snapshot's trend periods; null marks a missing period. */
  series?: Array<number | null>;
}) {
  const status = resolveStatus(measure);
  const interpretation = interpretationLabel(measure.change);
  const change = changeLabel(measure.change);
  return (
    <article className={`kpi-card kpi-${status}`} data-testid={`kpi-${measure.indicator_code ?? "unknown"}`}>
      <p className="kpi-label" title={measure.name ?? measure.indicator_code ?? undefined}>
        {measure.name ?? measure.indicator_code}
      </p>
      <div className="kpi-main">
        <p className="kpi-value">{formatMeasure(measure.raw_value, measure.unit, measure.display_value)}</p>
        {measure.raw_value !== null ? (
          <p className="kpi-delta">
            {measure.change?.change_kind ? (
              <Icon
                name={changeDirection(measure) ?? "flat"}
                size={14}
                className={`kpi-arrow interpretation-${measure.change?.interpretation ?? "not_interpreted"}`}
              />
            ) : null}
            {change}
            {interpretation ? (
              <span
                className={`kpi-interpretation interpretation-${measure.change?.interpretation ?? "not_interpreted"}`}
                title={measure.change?.interpretation_reason ?? undefined}
              >
                {" · "}
                {interpretation}
              </span>
            ) : null}
            {comparisonPeriod && measure.change?.change_kind ? (
              <span className="kpi-versus"> vs {periodLabel(comparisonPeriod)}</span>
            ) : null}
          </p>
        ) : null}
      </div>
      {measure.raw_value === null ? (
        <p className="kpi-unavailable" role="note">
          {unavailableLabel(measure.reason_code)}
        </p>
      ) : null}
      <div className="kpi-foot">
        <StatusPill status={status} />
        {series && measure.raw_value !== null ? <Sparkline values={series} /> : null}
      </div>
    </article>
  );
}

/** Arrow direction follows the sign of the server's change value; its colour follows the server's
 * interpretation, so a falling mortality rate can be an improvement. */
function changeDirection(measure: Measure): "up" | "down" | "flat" | null {
  const change = measure.change;
  const value = change?.percentage_point_change ?? change?.absolute_change ?? change?.relative_percent_change;
  if (value === null || value === undefined) {
    return null;
  }
  return value > 0 ? "up" : value < 0 ? "down" : "flat";
}

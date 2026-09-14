import { changeLabel, formatMeasure, interpretationLabel, resolveStatus, unavailableLabel } from "@/lib/status";
import type { Measure } from "@/lib/types";
import { StatusPill } from "./StatusPill";

export function KpiCard({ measure }: { measure: Measure }) {
  const status = resolveStatus(measure);
  const spark = measure.comparison?.raw_value;
  const interpretation = interpretationLabel(measure.change);
  return (
    <article className="card kpi-card" data-testid={`kpi-${measure.indicator_code ?? "unknown"}`}>
      <p className="kpi-label">{measure.name ?? measure.indicator_code}</p>
      <p className="kpi-value">{formatMeasure(measure.raw_value, measure.unit, measure.display_value)}</p>
      <p className="kpi-delta">
        {changeLabel(measure.change)}
        {interpretation ? (
          <span
            className={`kpi-interpretation interpretation-${measure.change?.interpretation ?? "not_interpreted"}`}
            title={measure.change?.interpretation_reason ?? undefined}
          >
            {" · "}
            {interpretation}
          </span>
        ) : null}
      </p>
      {measure.raw_value === null ? (
        <p className="kpi-unavailable" role="note">
          {unavailableLabel(measure.reason_code)}
        </p>
      ) : null}
      <StatusPill status={status} />
      {spark != null && measure.raw_value != null ? (
        <svg className="kpi-spark" viewBox="0 0 64 18" aria-hidden="true">
          <polyline
            fill="none"
            stroke="#0a4a7a"
            strokeWidth="2"
            points={`2,${16 - Math.min(14, spark / 10)} 62,${16 - Math.min(14, measure.raw_value / 10)}`}
          />
        </svg>
      ) : null}
    </article>
  );
}

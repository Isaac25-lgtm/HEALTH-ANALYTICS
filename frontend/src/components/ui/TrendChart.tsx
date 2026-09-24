import { periodLabel, shortPeriodLabel } from "@/lib/periods";
import type { DashboardResponse } from "@/lib/types";

const WIDTH = 560;
const HEIGHT = 170;
const LEFT = 38;
const RIGHT = 10;
const TOP = 10;
const BOTTOM = 26;

function niceStep(rough: number): number {
  const magnitude = 10 ** Math.floor(Math.log10(rough));
  const scaled = rough / magnitude;
  const factor = scaled <= 1 ? 1 : scaled <= 2 ? 2 : scaled <= 2.5 ? 2.5 : scaled <= 5 ? 5 : 10;
  return factor * magnitude;
}

/**
 * Plots server-calculated values for one indicator across the snapshot's trend periods. The only
 * arithmetic is screen positioning. Missing periods are gaps, never interpolated or zero.
 */
export function TrendChart({
  trends,
  indicatorCode,
}: {
  trends: DashboardResponse["module_result"]["trends"];
  indicatorCode?: string;
}) {
  const plotWidth = WIDTH - LEFT - RIGHT;
  const plotHeight = HEIGHT - TOP - BOTTOM;
  const series = trends.map((row, index) => {
    const measure = indicatorCode ? row.values[indicatorCode] : undefined;
    return {
      period: row.period,
      value: measure?.raw_value ?? null,
      display: measure?.display_value ?? null,
      unit: measure?.unit ?? null,
      x: LEFT + (trends.length === 1 ? plotWidth / 2 : (index * plotWidth) / Math.max(trends.length - 1, 1)),
    };
  });
  if (!series.some((item) => item.value != null)) {
    return <p className="panel-empty">No trend values are available for the selected indicator.</p>;
  }
  const percent = series.some((item) => item.unit === "%");
  const present = series.filter((item) => item.value != null).map((item) => item.value as number);
  const top = percent ? Math.max(100, ...present) : Math.max(...present, 0);
  const bottom = Math.min(0, ...present);
  // Axis ticks at round numbers (0, 25, 50 ... or 0, 2k, 4k ...); screen layout only.
  const step = niceStep((top - bottom) / 4 || 1);
  const min = Math.floor(bottom / step) * step;
  const max = Math.ceil(top / step) * step;
  const span = max - min || 1;
  const yFor = (value: number) => TOP + plotHeight - ((value - min) / span) * plotHeight;
  const ticks: number[] = [];
  for (let tick = min; tick <= max + step / 2; tick += step) {
    ticks.push(tick);
  }
  let path = "";
  let drawing = false;
  for (const item of series) {
    if (item.value == null) {
      drawing = false;
      continue;
    }
    path += `${drawing ? "L" : "M"}${item.x.toFixed(1)} ${yFor(item.value).toFixed(1)} `;
    drawing = true;
  }
  const labelEvery = Math.ceil(series.length / 8);
  return (
    <figure className="trend-figure">
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="trend-chart"
        role="img"
        aria-label={`Trend for ${indicatorCode ?? "the selected indicator"} across ${series.length} periods; missing periods are gaps`}
        preserveAspectRatio="xMidYMid meet"
      >
        {ticks.map((tick) => (
          <g key={tick}>
            <line x1={LEFT} x2={WIDTH - RIGHT} y1={yFor(tick)} y2={yFor(tick)} className="trend-grid" />
            <text x={LEFT - 6} y={yFor(tick) + 4} textAnchor="end" className="trend-axis">
              {Number.isInteger(tick) ? tick.toLocaleString() : tick.toFixed(1)}
              {percent ? "%" : ""}
            </text>
          </g>
        ))}
        <path d={path.trim()} className="trend-line" fill="none" />
        {series.map((item) =>
          item.value == null ? null : (
            <circle key={item.period} cx={item.x} cy={yFor(item.value)} r="3.2" className="trend-point">
              <title>
                {periodLabel(item.period)}: {item.display ?? item.value}
                {item.unit === "%" ? "%" : item.unit ? ` ${item.unit}` : ""}
              </title>
            </circle>
          ),
        )}
        {series.map((item, index) =>
          index % labelEvery === 0 ? (
            <text key={`label-${item.period}`} x={item.x} y={HEIGHT - 8} textAnchor="middle" className="trend-axis">
              {shortPeriodLabel(item.period)}
            </text>
          ) : null,
        )}
      </svg>
      <figcaption className="panel-note">Missing periods are gaps, not interpolated.</figcaption>
    </figure>
  );
}

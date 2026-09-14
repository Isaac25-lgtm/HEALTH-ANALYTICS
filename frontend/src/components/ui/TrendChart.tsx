import type { DashboardResponse } from "@/lib/types";

export function TrendChart({
  trends,
  indicatorCode,
}: {
  trends: DashboardResponse["module_result"]["trends"];
  indicatorCode?: string;
}) {
  const series = trends.map((row, index) => {
    const measure = indicatorCode ? row.values[indicatorCode] : undefined;
    return {
      period: row.period,
      value: measure?.raw_value ?? null,
      unit: measure?.unit ?? null,
      x: trends.length === 1 ? 32 : 8 + (index * 112) / Math.max(trends.length - 1, 1),
    };
  });
  if (!series.some((item) => item.value != null)) {
    return <p className="muted">No trend values are available for the selected indicator.</p>;
  }
  const percent = series.some((item) => item.unit === "%");
  const present = series.filter((item) => item.value != null).map((item) => item.value as number);
  const max = percent ? Math.max(100, ...present) : Math.max(...present, 0);
  const min = percent ? 0 : 0;
  const span = max - min || 1;
  const segments: string[] = [];
  let drawing = false;
  for (const item of series) {
    if (item.value == null) {
      drawing = false;
      continue;
    }
    const y = 52 - ((item.value - min) / span) * 40;
    segments.push(`${drawing ? "L" : "M"} ${item.x} ${y}`);
    drawing = true;
  }
  return (
    <figure>
      <svg viewBox="0 0 128 64" className="trend-chart" role="img" aria-label="Selected indicator trend with missing periods as gaps">
        <path d="M8 12 H120 M8 32 H120 M8 52 H120" stroke="#d7e8f5" strokeWidth="1" />
        <path d={segments.join(" ")} fill="none" stroke="#0a4a7a" strokeWidth="2" />
        {series.map((item) => {
          if (item.value == null) {
            return null;
          }
          const y = 52 - ((item.value - min) / span) * 40;
          return <circle key={item.period} cx={item.x} cy={y} r="2.5" fill="#06345a" />;
        })}
      </svg>
      <figcaption className="muted">
        Missing periods are gaps, not interpolated. Scale {min}–{max}
        {percent ? "%" : ""}. {series.map((item) => item.period).join(" · ")}
      </figcaption>
    </figure>
  );
}

/**
 * A decorative miniature of server-calculated values. Missing periods break the line; nothing is
 * interpolated or smoothed. Fewer than two present values draw nothing.
 */
export function Sparkline({ values }: { values: Array<number | null> }) {
  const present = values.filter((value): value is number => value !== null && Number.isFinite(value));
  if (present.length < 2) {
    return null;
  }
  const low = Math.min(...present);
  const high = Math.max(...present);
  const span = high - low || 1;
  const step = values.length > 1 ? 76 / (values.length - 1) : 0;
  let path = "";
  let drawing = false;
  values.forEach((value, index) => {
    if (value === null || !Number.isFinite(value)) {
      drawing = false;
      return;
    }
    const x = 2 + index * step;
    const y = 20 - ((value - low) / span) * 16;
    path += `${drawing ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)} `;
    drawing = true;
  });
  return (
    <svg className="sparkline" viewBox="0 0 80 22" aria-hidden="true" focusable="false">
      <path d={path.trim()} fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
    </svg>
  );
}

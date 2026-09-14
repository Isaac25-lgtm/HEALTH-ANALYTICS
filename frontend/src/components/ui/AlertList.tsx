import type { DashboardResponse } from "@/lib/types";

export function AlertList({
  insights,
  flags,
}: {
  insights: DashboardResponse["insights"];
  flags: DashboardResponse["module_result"]["quality_flags"];
}) {
  if (!insights.length && !flags.length) {
    return <p className="muted">No deterministic priority or quality insights for this scope.</p>;
  }
  return (
    <ul className="alert-list">
      {insights.map((item, index) => (
        <li key={`${item.code}-${index}`} className={`alert alert-${item.severity}`}>
          <strong>{item.title}</strong>
          <p>{item.detail}</p>
        </li>
      ))}
    </ul>
  );
}

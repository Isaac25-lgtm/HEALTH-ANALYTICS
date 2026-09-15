import Link from "next/link";
import type { DashboardResponse } from "@/lib/types";
import { Panel } from "./Panel";

const SEVERITY_ORDER: Record<string, number> = { critical: 0, high: 1, blocking: 1, error: 2, medium: 3, warning: 3 };
const SEVERITY_CUE: Record<string, string> = { critical: "!", high: "!", blocking: "!", error: "!", medium: "▲", warning: "▲" };

/**
 * A short, prioritised list of the server's deterministic insights. The complete list and every
 * data-quality flag live in the Data quality workspace, reached through "View all".
 */
export function InsightsPanel({
  dashboard,
  viewAllHref,
  limit = 4,
  title = "Priority insights",
  className,
}: {
  dashboard: DashboardResponse;
  viewAllHref: string;
  limit?: number;
  title?: string;
  className?: string;
}) {
  const ordered = [...dashboard.insights].sort(
    (a, b) => (SEVERITY_ORDER[a.severity] ?? 9) - (SEVERITY_ORDER[b.severity] ?? 9),
  );
  const shown = ordered.slice(0, limit);
  const flags = dashboard.module_result.quality_flags.length;
  const hidden = ordered.length - shown.length;
  return (
    <Panel
      title={title}
      subtitle="Deterministic findings from this snapshot"
      className={className}
      footer={
        <Link className="panel-link" href={viewAllHref}>
          View all {ordered.length} insights and {flags} quality flags →
        </Link>
      }
    >
      {shown.length ? (
        <ol className="insight-list">
          {shown.map((item, index) => (
            <li key={`${item.code}-${index}`} className={`insight insight-${item.severity}`}>
              <span className="insight-cue" aria-hidden="true">
                {SEVERITY_CUE[item.severity] ?? "i"}
              </span>
              <div>
                <p className="insight-title">{item.title}</p>
                <p className="insight-detail">{item.detail}</p>
              </div>
            </li>
          ))}
        </ol>
      ) : (
        <p className="panel-empty">No deterministic priority insights for this scope.</p>
      )}
      {hidden > 0 ? <p className="panel-note">{hidden} more in the full list.</p> : null}
    </Panel>
  );
}

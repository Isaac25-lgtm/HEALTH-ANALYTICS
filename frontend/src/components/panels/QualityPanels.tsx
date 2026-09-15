"use client";

import { useState } from "react";
import { unavailableLabel } from "@/lib/status";
import type { DashboardResponse } from "@/lib/types";
import { Panel, PanelTabs } from "./Panel";

const PAGE_SIZE = 8;

/** Counts the server already decided: open flags by severity and indicators without a value. */
export function QualitySummary({ dashboard, className }: { dashboard: DashboardResponse; className?: string }) {
  const flags = dashboard.module_result.quality_flags;
  const unavailable = dashboard.module_result.indicators.filter((row) => row.raw_value === null);
  const bySeverity = flags.reduce<Record<string, number>>((counts, flag) => {
    const key = flag.severity.toLowerCase();
    counts[key] = (counts[key] ?? 0) + 1;
    return counts;
  }, {});
  const stats = [
    { label: "Open flags", value: flags.length },
    ...Object.entries(bySeverity).map(([label, value]) => ({ label, value })),
    { label: "Indicators without a value", value: unavailable.length },
  ];
  return (
    <section className={`stat-strip ${className ?? ""}`} aria-label="Data quality summary">
      {stats.map((item) => (
        <div className="stat" key={item.label}>
          <span className="stat-label">{item.label}</span>
          <strong className="num">{item.value}</strong>
        </div>
      ))}
    </section>
  );
}

/** Paginated flags so a long run never becomes an endless page. */
export function QualityFlagsPanel({
  dashboard,
  className,
  compact,
}: {
  dashboard: DashboardResponse;
  className?: string;
  compact?: boolean;
}) {
  const flags = dashboard.module_result.quality_flags;
  const [page, setPage] = useState(0);
  const size = compact ? 5 : PAGE_SIZE;
  const pages = Math.max(1, Math.ceil(flags.length / size));
  const current = Math.min(page, pages - 1);
  const shown = flags.slice(current * size, current * size + size);
  return (
    <Panel
      icon="quality"
      title={compact ? "Data quality issues" : "Data-quality console"}
      subtitle={`${flags.length} open flag${flags.length === 1 ? "" : "s"} in this run`}
      className={className}
      footer={
        pages > 1 ? (
          <nav className="pager" aria-label="Flag pages">
            <button type="button" className="link-button" disabled={current === 0} onClick={() => setPage(current - 1)}>
              Previous
            </button>
            <span className="panel-note">
              Page {current + 1} of {pages}
            </span>
            <button
              type="button"
              className="link-button"
              disabled={current >= pages - 1}
              onClick={() => setPage(current + 1)}
            >
              Next
            </button>
          </nav>
        ) : undefined
      }
    >
      {shown.length && compact ? (
        <ul className="dq-issues">
          {shown.map((flag) => (
            <li key={flag.id}>
              <span className={`badge badge-${flag.severity.toLowerCase()}`}>{flag.severity}</span>
              <span className="dq-issue-text">
                <span className="mono">{flag.rule_id}</span>
                <span className="dq-issue-detail">{flag.explanation}</span>
              </span>
            </li>
          ))}
        </ul>
      ) : shown.length ? (
        <div className="table-wrap">
          <table className="data-table">
            <caption className="sr-only">Data-quality flags for this snapshot</caption>
            <thead>
              <tr>
                <th scope="col">Rule</th>
                <th scope="col">Severity</th>
                <th scope="col">Explanation</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((flag) => (
                <tr key={flag.id}>
                  <td className="mono">{flag.rule_id}</td>
                  <td>
                    <span className={`badge badge-${flag.severity.toLowerCase()}`}>{flag.severity}</span>
                  </td>
                  <td>{flag.explanation}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="panel-empty">No data-quality flags were raised for this calculation run.</p>
      )}
    </Panel>
  );
}

export function UnavailableIndicatorsPanel({ dashboard, className }: { dashboard: DashboardResponse; className?: string }) {
  const unavailable = dashboard.module_result.indicators.filter((row) => row.raw_value === null);
  const [tab, setTab] = useState<"reasons" | "rule">("reasons");
  return (
    <Panel
      icon="info"
      title="Why some indicators have no value"
      className={className}
      actions={
        <PanelTabs
          label="Unavailable indicator view"
          active={tab}
          onChange={setTab}
          tabs={[
            { key: "reasons", label: "Reasons" },
            { key: "rule", label: "Rule" },
          ]}
        />
      }
    >
      {tab === "rule" ? (
        <p className="panel-copy">
          A missing value is never shown as zero. Resolve reporting and denominator problems before reading a gap as a
          service problem.
        </p>
      ) : unavailable.length ? (
        <ul className="dq-list">
          {unavailable.map((row) => (
            <li key={row.indicator_code ?? row.name}>
              <strong>{row.name ?? row.indicator_code}</strong>
              <span> · {unavailableLabel(row.reason_code)}</span>
              {row.blue_reason ? <span className="panel-note"> — {row.blue_reason}</span> : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className="panel-empty">Every indicator in this module has a value.</p>
      )}
    </Panel>
  );
}

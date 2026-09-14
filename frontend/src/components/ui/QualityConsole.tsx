import type { DashboardResponse } from "@/lib/types";
import { unavailableLabel } from "@/lib/status";

/**
 * Data-quality workspace. Flags and non-assessable indicators come from the committed snapshot;
 * the browser only groups what the server already decided.
 */
export function QualityConsole({ dashboard }: { dashboard: DashboardResponse }) {
  const flags = dashboard.module_result.quality_flags;
  const unavailable = dashboard.module_result.indicators.filter((row) => row.raw_value === null);
  const bySeverity = flags.reduce<Record<string, number>>((counts, flag) => {
    counts[flag.severity] = (counts[flag.severity] ?? 0) + 1;
    return counts;
  }, {});
  return (
    <section className="card" aria-label="Data quality console">
      <h2>Data-quality console</h2>
      <div className="stat-row">
        <div className="stat">
          <span className="stat-label">Open flags</span>
          <strong className="num">{flags.length}</strong>
        </div>
        {Object.entries(bySeverity).map(([severity, count]) => (
          <div className="stat" key={severity}>
            <span className="stat-label">{severity.toLowerCase()}</span>
            <strong className="num">{count}</strong>
          </div>
        ))}
        <div className="stat">
          <span className="stat-label">Indicators without a value</span>
          <strong className="num">{unavailable.length}</strong>
        </div>
      </div>
      {flags.length ? (
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
              {flags.map((flag) => (
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
        <p className="muted">No data-quality flags were raised for this calculation run.</p>
      )}
      {unavailable.length ? (
        <>
          <h3>Why some indicators have no value</h3>
          <ul className="dq-list">
            {unavailable.map((row) => (
              <li key={row.indicator_code ?? row.name}>
                <strong>{row.name ?? row.indicator_code}</strong> · {unavailableLabel(row.reason_code)}
                {row.blue_reason ? <span className="muted"> — {row.blue_reason}</span> : null}
              </li>
            ))}
          </ul>
        </>
      ) : null}
      <p className="muted">
        A missing value is never shown as zero. Resolve reporting problems before reading a gap as a service problem.
      </p>
    </section>
  );
}

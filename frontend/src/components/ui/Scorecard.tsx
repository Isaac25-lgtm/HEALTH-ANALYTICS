import { formatMeasure, resolveStatus } from "@/lib/status";
import type { Measure } from "@/lib/types";
import { StatusPill } from "./StatusPill";

export function Scorecard({
  rows,
  onOpen,
}: {
  rows: Measure[];
  onOpen?: (measure: Measure) => void;
}) {
  return (
    <div className="table-wrap">
      <table className="data-table">
        <caption className="sr-only">Indicator scorecard</caption>
        <thead>
          <tr>
            <th scope="col">Indicator</th>
            <th scope="col">Value</th>
            <th scope="col">Unit</th>
            <th scope="col">Status</th>
            <th scope="col">Evidence</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const status = resolveStatus(row);
            return (
              <tr key={row.indicator_code ?? row.name ?? "row"}>
                <th scope="row">{row.name ?? row.indicator_code}</th>
                <td className="num">{formatMeasure(row.raw_value, null, row.display_value)}</td>
                <td>{row.unit ?? "—"}</td>
                <td>
                  <StatusPill status={status} />
                </td>
                <td>
                  <button type="button" className="link-button" onClick={() => onOpen?.(row)}>
                    Methodology
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

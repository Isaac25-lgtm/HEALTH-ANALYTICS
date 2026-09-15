"use client";

import Link from "next/link";
import { useState } from "react";
import { screenForLevel } from "@/lib/scope";
import { formatMeasure, resolveStatus } from "@/lib/status";
import type { DashboardResponse, Measure } from "@/lib/types";
import { StatusPill } from "../ui/StatusPill";
import type { LinkTarget } from "../workspaces/types";
import { Panel, PanelTabs } from "./Panel";

type UnitRow = {
  org_unit_id: string;
  org_unit_name: string;
  level_type?: string;
  facility_level?: string | null;
  values: Record<string, Measure>;
};

function statusCell(key: string, value: Measure | undefined) {
  const status = value ? resolveStatus(value) : "missing";
  return (
    <td key={key} className={`num cell cell-${status}`} title={value ? undefined : "No value in this snapshot"}>
      {formatMeasure(value?.raw_value ?? null, value?.unit === "%" ? null : value?.unit ?? null, value?.display_value)}
    </td>
  );
}

function UnitMatrix({
  rows,
  columns,
  hrefFor,
  filter,
  caption,
  showLevel,
}: {
  rows: UnitRow[];
  columns: Measure[];
  hrefFor: (row: UnitRow) => string;
  filter: string;
  caption: string;
  showLevel?: boolean;
}) {
  const visible = rows.filter((row) => row.org_unit_name.toLowerCase().includes(filter.toLowerCase()));
  if (!visible.length) {
    return <p className="panel-empty">No units match this view.</p>;
  }
  return (
    <div className="table-wrap">
      <table className="data-table matrix">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr>
            <th scope="col">Unit</th>
            {showLevel ? <th scope="col">Level</th> : null}
            {columns.map((column) => (
              <th
                key={column.indicator_code}
                scope="col"
                className="num matrix-head"
                title={column.indicator_code ?? undefined}
              >
                {column.name ?? column.indicator_code}
                {column.unit === "%" ? " (%)" : ""}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {visible.map((row) => (
            <tr key={row.org_unit_id}>
              <th scope="row">
                <Link href={hrefFor(row)}>{row.org_unit_name}</Link>
              </th>
              {showLevel ? <td>{row.facility_level ?? row.level_type ?? "—"}</td> : null}
              {columns.map((column) => statusCell(column.indicator_code ?? "", row.values[column.indicator_code ?? ""]))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Indicator-by-indicator scorecard with the evidence drawer on every row. */
export function IndicatorTable({ rows, onOpen }: { rows: Measure[]; onOpen: (measure: Measure) => void }) {
  return (
    <div className="table-wrap">
      <table className="data-table">
        <caption className="sr-only">Indicator scorecard</caption>
        <thead>
          <tr>
            <th scope="col">Indicator</th>
            <th scope="col" className="num">
              Value
            </th>
            <th scope="col">Status</th>
            <th scope="col">
              <span className="sr-only">Evidence</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.indicator_code ?? row.name ?? "row"}>
              <th scope="row">{row.name ?? row.indicator_code}</th>
              <td className="num">{formatMeasure(row.raw_value, row.unit, row.display_value)}</td>
              <td>
                <StatusPill status={resolveStatus(row)} />
              </td>
              <td>
                <button type="button" className="link-button" onClick={() => onOpen(row)}>
                  Evidence
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * The scorecard panel: child units against the headline indicators when the scope has children
 * (links drill down within the authorised scope), and the indicator list with evidence always.
 */
export function ScorecardPanel({
  dashboard,
  screen,
  hrefFor,
  onOpen,
  title,
  className,
  defaultView,
}: {
  dashboard: DashboardResponse;
  screen: string;
  hrefFor: (target: LinkTarget) => string;
  onOpen: (measure: Measure) => void;
  title?: string;
  className?: string;
  defaultView?: "units" | "indicators";
}) {
  const facilityView = screen === "district" || screen === "sub_county";
  const unitRows: UnitRow[] = facilityView
    ? dashboard.facility_scorecard.map((row) => ({ ...row, level_type: "facility" }))
    : dashboard.module_result.org_unit_comparison;
  const hasUnits = unitRows.length > 0;
  const [view, setView] = useState<"units" | "indicators">(defaultView ?? (hasUnits ? "units" : "indicators"));
  const [filter, setFilter] = useState("");
  const columns = dashboard.kpis.slice(0, 6);
  const heading =
    title ?? (facilityView ? "Facility performance scorecard" : hasUnits ? "Unit scorecard" : "Indicator scorecard");
  return (
    <Panel
      title={heading}
      className={className}
      subtitle={`${dashboard.period} · snapshot values`}
      actions={
        <>
          <PanelTabs
            label="Scorecard view"
            active={view}
            onChange={setView}
            tabs={[
              { key: "units", label: facilityView ? "Facilities" : "Units", disabled: !hasUnits },
              { key: "indicators", label: "Indicators" },
            ]}
          />
          {view === "units" && hasUnits ? (
            <input
              className="panel-filter"
              aria-label="Filter table"
              placeholder="Filter names"
              value={filter}
              onChange={(event) => setFilter(event.target.value)}
            />
          ) : null}
        </>
      }
    >
      {view === "units" && hasUnits ? (
        <UnitMatrix
          rows={unitRows}
          columns={columns}
          filter={filter}
          showLevel={facilityView}
          caption={facilityView ? "Facility comparison" : "Child unit comparison"}
          hrefFor={(row) =>
            hrefFor({
              screen: facilityView ? "facility" : screenForLevel(row.level_type),
              orgUnitId: row.org_unit_id,
            })
          }
        />
      ) : (
        <IndicatorTable rows={dashboard.module_result.indicators} onOpen={onOpen} />
      )}
    </Panel>
  );
}

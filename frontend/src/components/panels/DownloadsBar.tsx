"use client";

import { useState } from "react";
import { downloadExportFile, requestExport, waitForExport } from "@/lib/api";
import type { DashboardResponse } from "@/lib/types";
import { Icon, type IconName } from "../ui/Icon";

const FORMAT_ICONS: Record<string, IconName> = {
  excel: "sheet",
  powerpoint: "slides",
  report: "file",
  word: "file",
  pdf: "file",
};

const FORMAT_HINTS: Record<string, string> = {
  excel: "Data tables",
  powerpoint: "Presentation",
  report: "Narrative",
  word: "Document",
  pdf: "Report",
};

/**
 * Governed downloads for the displayed snapshot. Availability comes from the server; a file is
 * generated from the same analysis snapshot and view hash that produced the screen.
 */
export function DownloadsBar({
  dashboard,
  variant = "bar",
}: {
  dashboard: DashboardResponse;
  variant?: "bar" | "panel";
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const freshness = dashboard.module_result.freshness;
  const buttons = dashboard.exports.actions.map((action) => {
    const enabled = action.available && action.implemented && busy === null;
    return (
      <button
        key={action.kind}
        type="button"
        className={`download-button export-${action.kind}`}
        disabled={!enabled}
        title={action.message}
        onClick={async () => {
          setBusy(action.kind);
          setMessage(null);
          try {
            const created = await requestExport(action.kind, {
              org_unit_id: dashboard.scope.id,
              period: dashboard.period,
              module: dashboard.module,
              comparison_period: dashboard.comparison_period,
              analysis_snapshot_id: dashboard.analysis_snapshot_id,
              view_hash: dashboard.view_hash,
            });
            await waitForExport(created.job_id);
            await downloadExportFile(created.job_id);
            setMessage(created.message);
          } catch (err) {
            setMessage(err instanceof Error ? err.message : "Export failed.");
          } finally {
            setBusy(null);
          }
        }}
      >
        <Icon name={FORMAT_ICONS[action.kind] ?? "file"} size={22} className="download-icon" />
        <span className="download-text">
          <span className="download-label">{busy === action.kind ? "Generating…" : action.label}</span>
          <span className="download-hint" aria-hidden="true">
            {FORMAT_HINTS[action.kind] ?? action.format}
          </span>
        </span>
      </button>
    );
  });
  return (
    <section className={variant === "bar" ? "downloads-bar" : "panel downloads-panel"} aria-label="Downloads">
      <h2 className="downloads-title">
        <Icon name="download" size={20} />
        <span>Downloads</span>
      </h2>
      <div className="download-buttons">{buttons}</div>
      <p className="downloads-meta">
        {message ? <span role="status">{message} · </span> : null}
        Snapshot <span data-volatile>{dashboard.analysis_snapshot_id.slice(0, 8)}</span> · data{" "}
        {freshness.availability.replaceAll("_", " ")}
        {freshness.latest_extracted_at ? <span data-volatile> · extracted {freshness.latest_extracted_at}</span> : null}{" "}
        · platform-default templates (official MoH templates pending)
      </p>
    </section>
  );
}

"use client";

import { useEffect, useState } from "react";
import { getOpsStatus } from "@/lib/api";
import type { CurrentContext, DashboardResponse, OpsStatus } from "@/lib/types";
import { Panel } from "../panels/Panel";

/** Live registry health. Displayed values come from the control store, never stale prose. */
export function AdministrationPanels({
  dashboard,
  context,
  className,
}: {
  dashboard: DashboardResponse;
  context: CurrentContext;
  className?: string;
}) {
  const [ops, setOps] = useState<OpsStatus | null>(null);
  const [opsError, setOpsError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    if (!context.actions.includes("manage_users")) return () => undefined;
    getOpsStatus()
      .then((result) => {
        if (!cancelled) setOps(result);
      })
      .catch((error: Error) => {
        if (!cancelled) setOpsError(error.message);
      });
    return () => {
      cancelled = true;
    };
  }, [context.actions]);

  if (!context.actions.includes("manage_users")) {
    return (
      <Panel title="Administration" className={className}>
        <p className="banner-info" role="status">
          Your role does not include administration. The server enforces this regardless of navigation.
        </p>
      </Panel>
    );
  }

  const orgs = ops?.configuration.org_units;
  const mappedUnits = orgs
    ? Object.values(orgs.dhis2_mapped_by_level).reduce((total, value) => total + value, 0)
    : 0;
  const boundaryCount = Object.values(
    ops?.configuration.boundaries.current_by_level ?? {},
  ).reduce((total, value) => total + value, 0);
  const mappingCount =
    ops?.configuration.source_mappings.reduce((total, row) => total + row.enabled_rows, 0) ?? 0;
  const stagedCount = Object.values(
    ops?.configuration.population.staging_batches_by_status ?? {},
  ).reduce((total, value) => total + value, 0);
  const approvedPopulationVersions = ops?.configuration.population.versions_by_approval.approved ?? 0;
  const dhis2HasSucceeded =
    ops?.sync_jobs.freshness.some((row) => Boolean(row.last_success_at)) ?? false;
  const panels = [
    {
      title: "Populations",
      state: approvedPopulationVersions > 0 ? "ok" : "attention",
      detail:
        ops === null
          ? "Loading governed population registry status…"
          : `${stagedCount} staged batch(es), ${approvedPopulationVersions} approved version(s), ${ops.configuration.population.value_rows} applied value row(s). Selected scope: ${dashboard.population.status}.`,
    },
    {
      title: "Geography and boundaries",
      state: boundaryCount > 0 ? "ok" : "attention",
      detail:
        ops === null
          ? "Loading geography registry status…"
          : `${orgs?.total ?? 0} active analytical units; ${mappedUnits} have DHIS2 mappings; ${boundaryCount} current geometries. Selected map: ${dashboard.map.map_state.replaceAll("_", " ")}.`,
    },
    {
      title: "DHIS2 mappings",
      state: dhis2HasSucceeded && mappingCount > 0 ? "ok" : "attention",
      detail:
        ops === null
          ? "Loading connector status…"
          : `Connector: ${ops.dhis2.replaceAll("_", " ")}; ${mappingCount} enabled source mapping row(s) across ${ops.configuration.source_mappings.length} programme/version set(s).`,
    },
    {
      title: "Formula governance",
      state: ops && ops.configuration.formulas.undated_versions === 0 ? "ok" : "attention",
      detail:
        ops === null
          ? "Loading formula registry status…"
          : `${ops.configuration.formulas.dated_versions} of ${ops.configuration.formulas.total_versions} formula version(s) have effective dates.`,
    },
    {
      title: "AI providers",
      state: ops?.ai_enabled ? "ok" : "neutral",
      detail: ops?.ai_enabled
        ? "External AI interpretation is enabled; deterministic calculation remains authoritative."
        : "External AI is disabled. Deterministic evidence answers remain available.",
    },
    {
      title: "Templates",
      state: "neutral",
      detail: "Official Ministry templates are not supplied; exports use the labelled platform-default family.",
    },
    {
      title: "Programmes you administer",
      state: "ok",
      detail: context.programmes.join(", ") || "None",
    },
  ];
  return (
    <Panel icon="admin" title="Administration" subtitle="Live registry health and pending owner decisions" className={className}>
      <div className="health-grid">
        {panels.map((panel) => (
          <article key={panel.title} className={`health-card health-${panel.state}`}>
            <span className="stat-label">{panel.title}</span>
            <p>{panel.detail}</p>
          </article>
        ))}
      </div>
      {opsError ? <p className="banner-info">Operational status could not be loaded: {opsError}</p> : null}
      <p className="panel-note">
        Population imports, alias decisions, boundary activation and user provisioning run through audited server
        commands with separation of duties; see docs/DEPLOYMENT.md.
      </p>
    </Panel>
  );
}

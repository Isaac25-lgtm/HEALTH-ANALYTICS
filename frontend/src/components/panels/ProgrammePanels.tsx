"use client";

import { FormEvent, useState } from "react";
import { submitFacilityPopulation } from "@/lib/api";
import type { DashboardResponse } from "@/lib/types";
import { Panel, PanelTabs } from "./Panel";

/** Immunisation access-to-completion continuum exactly as returned by the server. */
export function ContinuumPanel({ dashboard, className }: { dashboard: DashboardResponse; className?: string }) {
  const continuum = dashboard.module_result.continuum;
  return (
    <Panel title="Immunisation continuum" subtitle="Access versus completion" className={className}>
      {continuum ? (
        <>
          <dl className="continuum-list">
            {Object.entries(continuum)
              .filter(([key]) => key !== "note")
              .map(([key, value]) => {
                const row = value && typeof value === "object" ? (value as Record<string, unknown>) : null;
                const raw = row && "raw_value" in row ? row.raw_value : null;
                return (
                  <div key={key}>
                    <dt>{key.replaceAll("_", " ")}</dt>
                    <dd>
                      {raw === null || raw === undefined ? "No data" : `${raw} ${row?.unit ?? ""}`.trim()}
                      {row?.threshold_state === "no_approved_threshold" ? (
                        <span className="panel-note"> · no approved threshold</span>
                      ) : null}
                    </dd>
                  </div>
                );
              })}
          </dl>
          <p className="panel-note">{String(continuum.note ?? "")}</p>
        </>
      ) : (
        <p className="panel-empty">The continuum is not available for this module and scope.</p>
      )}
    </Panel>
  );
}

/** MPDSR cause patterns under the server's disclosure rules, and active-review counts. */
export function MpdsrCausePanel({ dashboard, className }: { dashboard: DashboardResponse; className?: string }) {
  const mpdsr = dashboard.module_result.mpdsr;
  const [tab, setTab] = useState<"causes" | "reviews">("causes");
  const disclosure = mpdsr?.cause_disclosure;
  return (
    <Panel
      title="Cause patterns and reviews"
      subtitle={mpdsr?.cause_note ?? "Structured cause categories only"}
      className={className}
      actions={
        <PanelTabs
          label="MPDSR view"
          active={tab}
          onChange={setTab}
          tabs={[
            { key: "causes", label: "Cause patterns" },
            { key: "reviews", label: "Active reviews" },
          ]}
        />
      }
    >
      {!mpdsr ? (
        <p className="panel-empty">MPDSR extras are not available for this module.</p>
      ) : tab === "reviews" ? (
        mpdsr.active_events ? (
          <div className="stat-strip">
            <div className="stat">
              <span className="stat-label">{mpdsr.active_events.label ?? "Active reviews"}</span>
              <strong className="num">{mpdsr.active_events.count ?? "No data"}</strong>
            </div>
          </div>
        ) : (
          <p className="panel-empty">Active event counts are hidden without MPDSR event permission.</p>
        )
      ) : disclosure?.status === "disclosed" ? (
        <>
          <ul className="cause-list">
            {mpdsr.structured_cause_mentions.map((item) => (
              <li key={item.code ?? item.category}>
                <span>{item.category}</span>
                <strong className="num">{item.mentions}</strong>
              </li>
            ))}
          </ul>
          <p className="panel-note">
            Categories below {disclosure.min_cell_count} mentions or from a single reporting unit are suppressed (
            {disclosure.suppressed_categories ?? 0} suppressed).
          </p>
        </>
      ) : (
        <div className="withheld" role="status">
          <p className="withheld-title">Cause patterns withheld</p>
          <p className="panel-copy">{disclosure?.reason ?? "No approved disclosure policy applies."}</p>
        </div>
      )}
    </Panel>
  );
}

/** Facility metadata strip for the facility profile. */
export function FacilityIdentity({ dashboard }: { dashboard: DashboardResponse }) {
  const scope = dashboard.scope;
  return (
    <section className="identity-strip" aria-label="Facility details">
      <p>
        <strong>{scope.name}</strong>
        <span> · {scope.facility_level ?? scope.level_type}</span>
        <span> · {scope.ownership ?? "Ownership not recorded"}</span>
      </p>
      <p className="panel-note">
        {scope.district?.name ?? "District unknown"} / {scope.sub_county?.name ?? "Sub-county unknown"}
      </p>
    </section>
  );
}

/** Catchment-population workflow: a draft entry that cannot replace an approved denominator. */
export function CatchmentPanel({ dashboard, className }: { dashboard: DashboardResponse; className?: string }) {
  const [message, setMessage] = useState<string | null>(null);
  const population = dashboard.population;
  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    try {
      const result = await submitFacilityPopulation({
        org_unit_id: dashboard.scope.id,
        year: Number(data.get("year")),
        population: Number(data.get("population")),
        source_name: String(data.get("source_name")),
        reason: String(data.get("reason") || ""),
      });
      setMessage(`Draft catchment entry ${result.id} saved as ${result.status}. It is not used until approved.`);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Population entry failed.");
    }
  }
  return (
    <Panel title="Catchment population" subtitle="Draft entries need approval before use" className={className}>
      <p className="panel-copy">
        {population.status === "unavailable"
          ? `No approved population. ${population.reason ?? ""}`
          : `${population.population?.toLocaleString()} · ${population.year} · ${population.source ?? "source not stated"}`}
      </p>
      {dashboard.can_edit_population ? (
        <form className="compact-form" onSubmit={onSubmit}>
          <label>
            Year
            <input name="year" type="number" defaultValue={population.year ?? 2024} />
          </label>
          <label>
            Population
            <input name="population" type="number" min={1} required />
          </label>
          <label>
            Source
            <input name="source_name" required placeholder="Approved local source" />
          </label>
          <label>
            Reason
            <input name="reason" />
          </label>
          <button type="submit" className="primary-button">
            Save draft
          </button>
        </form>
      ) : (
        <p className="panel-note">Your role cannot submit catchment populations.</p>
      )}
      {message ? (
        <p className="panel-note" role="status">
          {message}
        </p>
      ) : null}
    </Panel>
  );
}

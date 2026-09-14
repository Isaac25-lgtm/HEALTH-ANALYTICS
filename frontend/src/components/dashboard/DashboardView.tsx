"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  downloadExportFile,
  getAnalysisSnapshot,
  getChildren,
  getContext,
  newRequestKey,
  queryDashboard,
  requestExport,
  submitFacilityPopulation,
  waitForExport,
} from "@/lib/api";
import { AskTheData } from "./AskTheData";
import {
  DEFAULT_COMPARISON,
  DEFAULT_PERIOD,
  MODULE_LABELS,
  PERIOD_OPTIONS,
  type DashboardLink,
  dashboardHref,
  screenForLevel,
  snapshotAnswersRequest,
} from "@/lib/scope";
import { formatMeasure, resolveStatus } from "@/lib/status";
import { sectionsFor, workspaceSpec } from "@/lib/workspaces";
import type { CurrentContext, DashboardResponse, Measure, OrgUnitSummary, RankingEntry } from "@/lib/types";
import { AdaptiveMap } from "../maps/AdaptiveMap";
import { AppShell } from "../shell/AppShell";
import { AlertList } from "../ui/AlertList";
import { ErrorState, LoadingState, PermissionDenied } from "../ui/EmptyStates";
import { EvidenceDrawer } from "../ui/EvidenceDrawer";
import { KpiCard } from "../ui/KpiCard";
import { Scorecard } from "../ui/Scorecard";
import { ExportHistory } from "../ui/ExportHistory";
import { QualityConsole } from "../ui/QualityConsole";
import { AdministrationPanels } from "../ui/AdministrationPanels";
import { StatusPill } from "../ui/StatusPill";
import { TrendChart } from "../ui/TrendChart";

type ApiError = Error & { status?: number };

export function DashboardView({
  screen,
  orgUnitId,
  period = DEFAULT_PERIOD,
  comparison,
  module,
  indicator,
  workspace,
  request,
  snapshot,
}: {
  screen: string;
  orgUnitId?: string;
  period?: string;
  comparison?: string;
  module?: string;
  indicator?: string;
  workspace?: string;
  request?: string;
  snapshot?: string;
}) {
  const router = useRouter();
  const [context, setContext] = useState<CurrentContext | null>(null);
  const [dashboard, setDashboard] = useState<DashboardResponse | null>(null);
  const [children, setChildren] = useState<OrgUnitSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [denied, setDenied] = useState<string | null>(null);
  const [selected, setSelected] = useState<Measure | null>(null);
  const [sortKey, setSortKey] = useState<"name" | "ranking">("name");
  const [query, setQuery] = useState("");
  const [exportMessage, setExportMessage] = useState<string | null>(null);
  const [exportBusy, setExportBusy] = useState<string | null>(null);
  const contextRef = useRef<CurrentContext | null>(null);
  const executedRef = useRef<DashboardResponse | null>(null);

  useEffect(() => {
    let cancelled = false;
    const current: DashboardLink = { screen, orgUnitId, period, comparison, module, indicator, workspace };

    async function load() {
      const next = contextRef.current ?? (await getContext());
      if (cancelled) {
        return;
      }
      contextRef.current = next;
      setContext(next);
      const landing = next.landing_org_unit;
      const targetId = orgUnitId ?? landing?.id;
      if (!targetId) {
        setError("No authorised landing geography is assigned.");
        return;
      }
      const expected = screenForLevel(landing?.level_type);
      if (!orgUnitId && !workspace && expected !== screen) {
        router.replace(dashboardHref({ ...current, screen: expected, orgUnitId: landing?.id }));
        return;
      }

      let result: DashboardResponse;
      if (snapshot) {
        // Refresh and shared links re-open the committed snapshot read-only.
        const executed = executedRef.current;
        if (executed?.analysis_snapshot_id === snapshot) {
          result = executed;
        } else {
          try {
            result = await getAnalysisSnapshot(snapshot);
          } catch (err) {
            if ((err as ApiError).status === 404) {
              router.replace(dashboardHref({ ...current, orgUnitId: targetId, request: newRequestKey() }));
              return;
            }
            throw err;
          }
          if (!snapshotAnswersRequest(result, { orgUnitId, period, module })) {
            router.replace(dashboardHref({ ...current, orgUnitId: targetId, request: newRequestKey() }));
            return;
          }
        }
      } else {
        if (!request) {
          // One idempotency key per navigation: repeated submissions reuse the same snapshot.
          router.replace(dashboardHref({ ...current, orgUnitId: targetId, request: newRequestKey() }));
          return;
        }
        result = await queryDashboard({
          orgUnitId: targetId,
          period,
          comparison,
          module,
          indicator,
          requestKey: request,
        });
        executedRef.current = result;
      }
      if (cancelled) {
        return;
      }
      const committed: DashboardLink = {
        ...current,
        orgUnitId: result.scope.id,
        module: module ?? result.module,
        request: result.request_key ?? request,
        snapshot: result.analysis_snapshot_id,
      };
      if (!workspace && result.screen !== screen && result.screen !== "sub_county") {
        router.replace(dashboardHref({ ...committed, screen: result.screen }));
        return;
      }
      setDashboard(result);
      if (!snapshot) {
        router.replace(dashboardHref(committed));
      }
      const nextChildren = await getChildren(result.scope.id).catch(() => []);
      if (!cancelled) {
        setChildren(nextChildren);
      }
    }

    load().catch((err: ApiError) => {
      if (cancelled) {
        return;
      }
      if (err.status === 401) {
        router.replace("/login");
        return;
      }
      if (err.status === 403) {
        setDenied(err.message);
        return;
      }
      setError(err.message);
    });
    return () => {
      cancelled = true;
    };
  }, [comparison, indicator, module, orgUnitId, period, request, router, screen, snapshot, workspace]);

  const geographyOptions = useMemo(() => {
    if (!context) {
      return [];
    }
    const seen = new Map<string, OrgUnitSummary>();
    for (const unit of [...context.geography_scopes, ...context.landing_org_units, ...children]) {
      seen.set(unit.id, unit);
    }
    if (dashboard) {
      seen.set(dashboard.scope.id, dashboard.scope);
    }
    return [...seen.values()];
  }, [children, context, dashboard]);

  if (denied) {
    return <PermissionDenied message={denied} />;
  }
  if (error) {
    return <ErrorState message={error} />;
  }
  if (!context || !dashboard) {
    return <LoadingState />;
  }

  function navigate(next: Partial<{ orgUnitId: string; period: string; comparison: string; module: string; indicator: string; screen: string }>) {
    router.push(
      dashboardHref({
        screen: next.screen ?? screen,
        orgUnitId: next.orgUnitId ?? dashboard?.scope.id ?? orgUnitId,
        period: next.period ?? period,
        comparison: next.comparison ?? comparison,
        module: next.module ?? module ?? dashboard?.module,
        indicator: next.indicator ?? indicator,
        workspace,
        request: newRequestKey(),
      }),
    );
  }

  const selectedCode = dashboard.selected_indicator ?? dashboard.ranking.indicator_code;
  const rankingOrder = new Map(dashboard.ranking.ordered_org_unit_ids.map((id, index) => [id, index]));
  const comparisonRows = dashboard.module_result.org_unit_comparison
    .filter((row) => row.org_unit_name.toLowerCase().includes(query.toLowerCase()))
    .sort((a, b) => {
      if (sortKey === "ranking" && dashboard.ranking.ranking_allowed) {
        return (rankingOrder.get(a.org_unit_id) ?? Infinity) - (rankingOrder.get(b.org_unit_id) ?? Infinity);
      }
      return a.org_unit_name.localeCompare(b.org_unit_name);
    });
  const excluded = dashboard.ranking.excluded ?? { blue: [], missing: [], non_assessable: [] };
  const mpdsr = dashboard.module_result.mpdsr;
  const freshness = dashboard.module_result.freshness;

  const spec = workspaceSpec(workspace);
  const visible = new Set(sectionsFor(workspace));
  const shows = (section: string) => visible.has(section as never);

  return (
    <AppShell context={context} screen={screen} workspace={workspace}>
      <form
        className="filter-bar"
        onSubmit={(event) => {
          event.preventDefault();
          const data = new FormData(event.currentTarget);
          navigate({
            orgUnitId: String(data.get("orgUnitId")),
            period: String(data.get("period")),
            comparison: String(data.get("comparison")),
            module: String(data.get("module")),
            indicator: String(data.get("indicator") || ""),
          });
        }}
      >
        <label>
          Geography
          <select name="orgUnitId" defaultValue={dashboard.scope.id} aria-label="Geography">
            {geographyOptions.map((unit) => (
              <option key={unit.id} value={unit.id}>
                {unit.name} ({unit.level_type})
              </option>
            ))}
          </select>
        </label>
        <label>
          Period
          <select name="period" defaultValue={dashboard.period} aria-label="Period">
            {PERIOD_OPTIONS.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
        <label>
          Comparison
          <select
            name="comparison"
            defaultValue={dashboard.comparison_period ?? comparison ?? DEFAULT_COMPARISON}
            aria-label="Comparison period"
          >
            {PERIOD_OPTIONS.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
        <label>
          Programme module
          <select name="module" defaultValue={dashboard.module} aria-label="Programme module">
            {dashboard.available_modules.map((code) => (
              <option key={code} value={code}>
                {MODULE_LABELS[code] ?? code}
              </option>
            ))}
          </select>
        </label>
        <label>
          Indicator
          <select name="indicator" defaultValue={selectedCode} aria-label="Selected indicator">
            {dashboard.module_result.indicators.map((row) => (
              <option key={row.indicator_code ?? row.name} value={row.indicator_code ?? ""}>
                {row.name ?? row.indicator_code}
              </option>
            ))}
          </select>
        </label>
        <button type="submit" className="primary-button">
          Apply
        </button>
      </form>

      <p className="workspace-kicker">
        <strong>{spec ? spec.label : `${screen.replaceAll("_", " ")} geography`}</strong>
        {" · "}
        {spec ? spec.summary : `Composed for ${dashboard.scope.level_type} scope.`}
      </p>
      <p className="freshness">
        Source freshness: {freshness.availability.replaceAll("_", " ")}
        {freshness.latest_source_freshness_at ? ` · source ${freshness.latest_source_freshness_at}` : ""}
        {freshness.latest_extracted_at ? ` · extracted ${freshness.latest_extracted_at}` : ""}
        {" · "}run {dashboard.module_result.current_run_id}
        {" · "}snapshot {dashboard.analysis_snapshot_id}
        {dashboard.snapshot_created_at ? ` · committed ${dashboard.snapshot_created_at}` : ""}{" "}
        <button type="button" className="link-button" onClick={() => navigate({})}>
          Recalculate from current data
        </button>
      </p>

      {dashboard.population.status === "unavailable" ? (
        <div className="banner-info" role="status">
          Approved population is unavailable. Population-derived indicators are non-assessable. Service-derived
          indicators remain visible. Missing population is not treated as zero.
          {dashboard.population.reason ? ` ${dashboard.population.reason}` : ""}
          {dashboard.can_edit_population ? " An authorised catchment entry can be submitted below." : ""}
        </div>
      ) : (
        <p className="muted">
          Population {dashboard.population.population?.toLocaleString()} · year {dashboard.population.year} ·{" "}
          {dashboard.population.source ?? "source not stated"} · {dashboard.population.approval_status ?? "n/a"}
        </p>
      )}

      {shows("identity") && screen === "facility" ? (
        <section className="card identity-strip">
          <p>
            <strong>{dashboard.scope.name}</strong> · {dashboard.scope.facility_level ?? dashboard.scope.level_type} ·{" "}
            {dashboard.scope.ownership ?? "Ownership not recorded"}
          </p>
          <p className="muted">
            {dashboard.scope.district?.name ?? "District unknown"} / {dashboard.scope.sub_county?.name ?? "Sub-county unknown"}
          </p>
        </section>
      ) : null}

      {shows("kpis") ? (
      <section className="kpi-row" aria-label="Key indicators">
        {dashboard.kpis.map((measure) => (
          <KpiCard key={measure.indicator_code} measure={measure} />
        ))}
      </section>
      ) : null}

      {shows("continuum") && dashboard.module_result.continuum ? (
        <section className="card" aria-label="Immunization continuum">
          <h2>Immunization continuum</h2>
          <p className="muted">{String(dashboard.module_result.continuum.note ?? "")}</p>
          <dl className="continuum-list">
            {Object.entries(dashboard.module_result.continuum)
              .filter(([key]) => key !== "note")
              .map(([key, value]) => {
                const row = value && typeof value === "object" ? (value as Record<string, unknown>) : null;
                return (
                  <div key={key}>
                    <dt>{key.replaceAll("_", " ")}</dt>
                    <dd>
                      {row && "raw_value" in row
                        ? `${row.raw_value ?? "No data"} ${row.unit ?? ""}`.trim()
                        : "Not available"}
                      {row?.threshold_state === "no_approved_threshold" ? " · threshold TBD" : ""}
                    </dd>
                  </div>
                );
              })}
          </dl>
        </section>
      ) : null}
      {shows("mpdsr") && mpdsr ? (
        <section className="card" aria-label="MPDSR extras">
          <h2>MPDSR process extras</h2>
          <p className="muted">{mpdsr.cause_note ?? ""}</p>
          {mpdsr.cause_disclosure?.status === "disclosed" ? (
            <>
              <ul>
                {mpdsr.structured_cause_mentions.map((item) => (
                  <li key={item.category}>
                    {item.category}: {item.mentions} mentions
                  </li>
                ))}
              </ul>
              <p className="muted">
                Categories below {mpdsr.cause_disclosure.min_cell_count} mentions or from a single reporting unit are
                suppressed ({mpdsr.cause_disclosure.suppressed_categories ?? 0} suppressed).
              </p>
            </>
          ) : (
            <p className="muted">
              Cause patterns withheld: {mpdsr.cause_disclosure?.reason ?? "no approved disclosure policy applies."}
            </p>
          )}
          {mpdsr.active_events ? (
            <p>
              {mpdsr.active_events.label}: {mpdsr.active_events.count}
            </p>
          ) : (
            <p className="muted">Active event counts are hidden without MPDSR event permission.</p>
          )}
        </section>
      ) : null}

      {shows("map") || shows("insights") ? (
      <section className="grid-2">
        {shows("map") ? (
        <article className="card">
          <h2>Geographic intelligence</h2>
          <AdaptiveMap dashboard={dashboard} period={dashboard.period} comparison={comparison} />
        </article>
        ) : null}
        {shows("insights") ? (
        <article className="card">
          <h2>Priority and quality insights</h2>
          <AlertList insights={dashboard.insights} flags={dashboard.module_result.quality_flags} />
        </article>
        ) : null}
      </section>
      ) : null}

      {shows("scorecard") ? (
      <section className="card">
        <div className="card-head">
          <h2>{screen === "district" ? "Facility performance scorecard" : "Scorecard"}</h2>
          <input
            aria-label="Filter table"
            placeholder="Filter names"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
        {screen === "district" ? (
          <div className="table-wrap">
            <table className="data-table">
              <caption className="sr-only">Facility comparison</caption>
              <thead>
                <tr>
                  <th>Facility</th>
                  <th>Level</th>
                  <th>Ownership</th>
                  {dashboard.kpis.map((measure) => (
                    <th key={measure.indicator_code}>{measure.indicator_code}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {dashboard.facility_scorecard
                  .filter((row) => row.org_unit_name.toLowerCase().includes(query.toLowerCase()))
                  .map((row) => (
                    <tr key={row.org_unit_id}>
                      <th scope="row">
                        <a
                          href={dashboardHref({
                            screen: "facility",
                            orgUnitId: row.org_unit_id,
                            period: dashboard.period,
                            comparison,
                            module: dashboard.module,
                          })}
                        >
                          {row.org_unit_name}
                        </a>
                      </th>
                      <td>{row.facility_level ?? "—"}</td>
                      <td>{row.ownership ?? "—"}</td>
                      {dashboard.kpis.map((measure) => {
                        const value = row.values[measure.indicator_code ?? ""];
                        return (
                          <td key={measure.indicator_code} className="num">
                            {formatMeasure(value?.raw_value ?? null, value?.unit ?? null, value?.display_value)}
                            <StatusPill status={value ? resolveStatus(value) : "missing"} />
                          </td>
                        );
                      })}
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Scorecard rows={dashboard.module_result.indicators} onOpen={setSelected} />
        )}
      </section>
      ) : null}

      {shows("children") && comparisonRows.length ? (
        <section className="card">
          <div className="card-head">
            <h2>Child geography comparison</h2>
            {dashboard.ranking.ranking_allowed ? (
              <button
                type="button"
                className="link-button"
                onClick={() => setSortKey(sortKey === "name" ? "ranking" : "name")}
              >
                Sort by {sortKey === "name" ? "approved ranking" : "name"}
              </button>
            ) : null}
          </div>
          <ul className="comparison-list">
            {comparisonRows.map((row) => {
              const value = selectedCode ? row.values[selectedCode] : undefined;
              return (
                <li key={row.org_unit_id}>
                  <a
                    href={dashboardHref({
                      screen: screenForLevel(row.level_type),
                      orgUnitId: row.org_unit_id,
                      period: dashboard.period,
                      comparison,
                      module: dashboard.module,
                    })}
                  >
                    {row.org_unit_name}
                  </a>
                  <span className="num">{formatMeasure(value?.raw_value ?? null, value?.unit ?? null, value?.display_value)}</span>
                  <StatusPill status={value ? resolveStatus(value) : "missing"} />
                </li>
              );
            })}
          </ul>
        </section>
      ) : null}

      {shows("trend") || shows("ranking") ? (
      <section className="grid-2">
        {shows("trend") ? (
        <article className="card">
          <h2>Trend</h2>
          <TrendChart trends={dashboard.module_result.trends} indicatorCode={selectedCode} />
        </article>
        ) : null}
        {shows("ranking") ? (
        <article className="card">
          <h2>Selected-indicator ranking</h2>
          {dashboard.ranking.ranking_allowed ? (
            <RankingLists ranking={dashboard.ranking} />
          ) : (
            <p className="muted">{dashboard.ranking.reason}</p>
          )}
          {excluded.blue.length || excluded.missing.length || excluded.non_assessable.length ? (
            <p className="muted">
              Not ranked: {excluded.blue.length} BLUE (non-assessable data quality), {excluded.missing.length} without a
              value, {excluded.non_assessable.length} without an approved status.
            </p>
          ) : null}
        </article>
        ) : null}
      </section>
      ) : null}

      {shows("population") && screen === "facility" && dashboard.can_edit_population ? (
        <PopulationForm orgUnitId={dashboard.scope.id} year={dashboard.population.year ?? 2024} />
      ) : null}

      {shows("quality") ? <QualityConsole dashboard={dashboard} /> : null}

      {shows("administration") ? <AdministrationPanels dashboard={dashboard} context={context} /> : null}

      {shows("ask") ? (
        <AskTheData dashboard={dashboard} period={dashboard.period} comparison={comparison} />
      ) : null}

      {shows("exports") ? (
      <section className="card export-surface">
        <h2>Exports</h2>
        <p className="muted">
          Files are generated from the displayed analytical snapshot {dashboard.analysis_snapshot_id}. Official MoH
          branding templates are still pending, so outputs use the labelled platform-default family.
        </p>
        <div className="export-actions">
          {dashboard.exports.actions.map((action) => {
            const enabled = action.available && action.implemented && exportBusy === null;
            return (
              <button
                key={action.kind}
                type="button"
                className={`export-${action.kind}`}
                disabled={!enabled}
                title={action.message}
                onClick={async () => {
                  setExportBusy(action.kind);
                  setExportMessage(null);
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
                    setExportMessage(created.message);
                  } catch (err) {
                    setExportMessage(err instanceof Error ? err.message : "Export failed.");
                  } finally {
                    setExportBusy(null);
                  }
                }}
              >
                {exportBusy === action.kind ? "Generating…" : action.label}
              </button>
            );
          })}
        </div>
        {exportMessage ? <p className="muted">{exportMessage}</p> : null}
      </section>
      ) : null}

      {shows("exportHistory") ? <ExportHistory /> : null}

      <EvidenceDrawer measure={selected} onClose={() => setSelected(null)} />
    </AppShell>
  );
}

const ORDER_RULE_LABELS: Record<string, string> = {
  higher_values_rank_first: "Higher values rank first for this indicator.",
  lower_values_rank_first: "Lower values rank first for this indicator.",
  closest_to_desired_range_ranks_first: "Values closest to the approved desired range rank first.",
};

function RankingLists({ ranking }: { ranking: DashboardResponse["ranking"] }) {
  const entry = (row: RankingEntry) => (
    <li key={row.org_unit_id}>
      {row.org_unit_name ?? row.org_unit_code} · {formatMeasure(row.raw_value, row.unit ?? null, row.display_value)}
    </li>
  );
  return (
    <>
      <p className="muted">{ranking.order_rule ? ORDER_RULE_LABELS[ranking.order_rule] ?? ranking.order_rule : null}</p>
      <div className="grid-2">
        <div>
          <h3>Best performing</h3>
          <ol>{ranking.best.map(entry)}</ol>
        </div>
        <div>
          <h3>Needs attention</h3>
          <ol>{ranking.worst.map(entry)}</ol>
        </div>
      </div>
    </>
  );
}

function PopulationForm({ orgUnitId, year }: { orgUnitId: string; year: number }) {
  const [message, setMessage] = useState<string | null>(null);
  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    try {
      const result = await submitFacilityPopulation({
        org_unit_id: orgUnitId,
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
    <form className="card" onSubmit={onSubmit}>
      <h2>Submit facility catchment population</h2>
      <p className="muted">Draft values cannot replace an approved denominator.</p>
      <div className="filter-bar">
        <label>
          Year
          <input name="year" type="number" defaultValue={year} />
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
      </div>
      {message ? <p className="muted">{message}</p> : null}
    </form>
  );
}

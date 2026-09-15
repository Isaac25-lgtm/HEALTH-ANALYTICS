"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { getAnalysisSnapshot, getChildren, getContext, newRequestKey, queryDashboard } from "@/lib/api";
import {
  DEFAULT_PERIOD,
  type DashboardLink,
  dashboardHref,
  screenForLevel,
  snapshotAnswersRequest,
} from "@/lib/scope";
import { compositionFor, SCREEN_TITLES, workspaceSpec } from "@/lib/workspaces";
import type { CurrentContext, DashboardResponse, Measure, OrgUnitSummary } from "@/lib/types";
import { AppShell } from "../shell/AppShell";
import { ErrorState, LoadingState, PermissionDenied } from "../ui/EmptyStates";
import { EvidenceDrawer } from "../ui/EvidenceDrawer";
import { COMPOSITIONS } from "../workspaces/registry";
import type { LinkTarget } from "../workspaces/types";
import { FilterStrip, StatusLine } from "./DashboardFrame";

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

  const current = dashboard;
  const hrefFor = (target: LinkTarget) =>
    dashboardHref({
      screen: target.screen ?? screen,
      orgUnitId: target.orgUnitId ?? current.scope.id,
      period: current.period,
      comparison,
      module: target.workspace ? undefined : target.module ?? current.module,
      workspace: target.workspace,
    });
  const spec = workspaceSpec(workspace);
  const Composition = COMPOSITIONS[compositionFor(screen, workspace)];
  const title = spec ? spec.label : SCREEN_TITLES[screen] ?? "Overview";

  return (
    <AppShell
      context={context}
      screen={screen}
      workspace={workspace}
      subtitle={`${title} · ${current.scope.name}`}
      alerts={{ count: current.module_result.quality_flags.length, href: hrefFor({ workspace: "quality" }) }}
    >
      <FilterStrip
        dashboard={current}
        context={context}
        geographyOptions={geographyOptions}
        comparison={comparison}
        onApply={(change) => navigate(change)}
      />
      <StatusLine
        dashboard={current}
        kicker={spec ? `${spec.label}: ${spec.summary}` : `${title} for ${current.scope.level_type.replaceAll("_", " ")} scope`}
        onRecalculate={() => navigate({})}
      />
      <Composition
        dashboard={current}
        context={context}
        screen={screen}
        comparison={comparison}
        onOpenEvidence={setSelected}
        hrefFor={hrefFor}
      />
      <EvidenceDrawer measure={selected} onClose={() => setSelected(null)} />
    </AppShell>
  );
}

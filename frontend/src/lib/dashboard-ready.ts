import type { CurrentContext, DashboardResponse, OrgUnitSummary } from "./types";

export type ReadyDashboard = { context: CurrentContext; dashboard: DashboardResponse; children: OrgUnitSummary[] };

// A one-navigation handoff, in memory only. No tokens, browser storage or shared-user cache.
let ready: { bundle: ReadyDashboard; expires: number } | null = null;

export function primeDashboard(bundle: ReadyDashboard): void {
  ready = { bundle, expires: Date.now() + 30_000 };
}

export function readReadyDashboard(snapshot?: string): ReadyDashboard | null {
  if (!ready || ready.expires <= Date.now() || ready.bundle.dashboard.analysis_snapshot_id !== snapshot) {
    return null;
  }
  return ready.bundle;
}

export function clearReadyDashboard(): void {
  ready = null;
}

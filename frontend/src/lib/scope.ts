export const PERIOD_OPTIONS = ["FY2024/25", "FY2025/26", "FY2026/27"] as const;
// Defaults follow the configured period list. Adding an owner-approved period advances the default
// without a second hard-coded year that can silently drift out of sync.
export const DEFAULT_PERIOD = PERIOD_OPTIONS[PERIOD_OPTIONS.length - 1];
export const DEFAULT_COMPARISON = PERIOD_OPTIONS[PERIOD_OPTIONS.length - 2];

const SCREEN_BY_LEVEL: Record<string, string> = {
  country: "national",
  region: "regional",
  sub_region: "regional",
  district: "district",
  city: "district",
  sub_county: "sub_county",
  facility: "facility",
};

export const WORKSPACES = [
  { href: "/dashboard/national", label: "Overview", screen: "national" },
  { href: "/workspace/anc", label: "ANC/MNCH", module: "anc" },
  { href: "/workspace/intrapartum", label: "Intrapartum and Newborn", module: "intrapartum" },
  { href: "/workspace/immunization", label: "Immunization", module: "immunization" },
  { href: "/workspace/mpdsr", label: "MPDSR", module: "mpdsr" },
  { href: "/workspace/maps", label: "Maps" },
  { href: "/workspace/trends", label: "Trends" },
  { href: "/workspace/quality", label: "Data Quality" },
  { href: "/workspace/reports", label: "Reports and Exports" },
  { href: "/workspace/ai", label: "AI Insights" },
  { href: "/workspace/admin", label: "Administration", admin: true },
] as const;

export function screenForLevel(levelType: string | null | undefined): string {
  if (!levelType) {
    return "national";
  }
  return SCREEN_BY_LEVEL[levelType] ?? "national";
}

export type DashboardLink = {
  screen?: string;
  orgUnitId?: string | null;
  period?: string;
  comparison?: string;
  module?: string;
  indicator?: string;
  /** Idempotency key for one analytical execution. */
  request?: string;
  /** A committed snapshot to re-open read-only (refresh never recalculates). */
  snapshot?: string;
  /** Workspace route to stay on instead of the geography screen route. */
  workspace?: string;
};

export function dashboardHref(options: DashboardLink): string {
  const screen = options.screen ?? "national";
  const params = new URLSearchParams();
  if (options.orgUnitId) {
    params.set("orgUnitId", options.orgUnitId);
  }
  params.set("period", options.period ?? DEFAULT_PERIOD);
  if (options.comparison) {
    params.set("comparison", options.comparison);
  }
  if (options.module) {
    params.set("module", options.module);
  }
  if (options.indicator) {
    params.set("indicator", options.indicator);
  }
  if (options.request) {
    params.set("request", options.request);
  }
  if (options.snapshot) {
    params.set("snapshot", options.snapshot);
  }
  const base = options.workspace ? `/workspace/${options.workspace}` : `/dashboard/${screen}`;
  return `${base}?${params.toString()}`;
}

/** A committed snapshot is only reused when it answers the geography, period and module in the URL. */
export function snapshotAnswersRequest(
  result: { scope: { id: string }; period: string; module: string },
  request: { orgUnitId?: string; period: string; module?: string },
): boolean {
  if (request.orgUnitId && result.scope.id !== request.orgUnitId) {
    return false;
  }
  if (result.period !== request.period) {
    return false;
  }
  return !request.module || result.module === request.module;
}

export const MODULE_LABELS: Record<string, string> = {
  anc: "ANC",
  intrapartum: "Intrapartum & newborn",
  immunization: "Immunisation",
  mpdsr: "MPDSR",
};

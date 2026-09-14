import type {
  AiResponse,
  CurrentContext,
  DashboardQuery,
  DashboardResponse,
  MapFeatureCollection,
  OrgUnitSummary,
} from "./types";

export type { CurrentContext, OrgUnitSummary };

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const CSRF_COOKIE = "hpip_csrf";

function readCookie(name: string): string | null {
  if (typeof document === "undefined") {
    return null;
  }
  const prefix = `${name}=`;
  const found = document.cookie.split("; ").find((part) => part.startsWith(prefix));
  return found ? decodeURIComponent(found.slice(prefix.length)) : null;
}

function csrfToken(): string | null {
  return readCookie(CSRF_COOKIE);
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const method = (init?.method ?? "GET").toUpperCase();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((init?.headers as Record<string, string> | undefined) ?? {}),
  };
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    const csrf = csrfToken();
    if (csrf) {
      headers["X-CSRF-Token"] = csrf;
    }
  }
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    credentials: "include",
    headers,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const message = body?.detail?.message ?? body?.message ?? response.statusText;
    const error = new Error(message) as Error & { status?: number; code?: string };
    error.status = response.status;
    error.code = body?.detail?.code;
    throw error;
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return response.json() as Promise<T>;
}

export async function login(username: string, password: string): Promise<{ ok: boolean; csrf_token: string }> {
  return api("/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export async function logout(): Promise<void> {
  await api("/auth/logout", { method: "POST" });
}

export async function getContext(): Promise<CurrentContext> {
  return api<CurrentContext>("/me/context");
}

export async function getChildren(orgUnitId: string): Promise<OrgUnitSummary[]> {
  return api<OrgUnitSummary[]>(`/org-units/${orgUnitId}/children`);
}

/** A client-generated key that makes a repeated submission return the same committed snapshot. */
export function newRequestKey(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `req-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

/**
 * Execute the analytical calculation. This is a CSRF-protected POST that commits one
 * snapshot; re-sending the same request key returns that snapshot without new runs.
 */
export async function queryDashboard(params: DashboardQuery): Promise<DashboardResponse> {
  const body: Record<string, string> = {
    org_unit_id: params.orgUnitId,
    period: params.period,
    request_key: params.requestKey,
  };
  if (params.module) {
    body.module = params.module;
  }
  if (params.comparison) {
    body.comparison_period = params.comparison;
  }
  if (params.indicator) {
    body.selected_indicator = params.indicator;
  }
  return api<DashboardResponse>("/analytics/dashboard/query", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** Read an already committed snapshot. Read-only: never recalculates. */
export async function getAnalysisSnapshot(snapshotId: string, signal?: AbortSignal): Promise<DashboardResponse> {
  return api<DashboardResponse>(`/analysis-snapshots/${encodeURIComponent(snapshotId)}`, { signal });
}

/** Map features for exactly the snapshot's map cohort, valued from the snapshot. */
export async function getSnapshotMapFeatures(snapshotId: string, signal?: AbortSignal): Promise<MapFeatureCollection> {
  return api<MapFeatureCollection>(
    `/analysis-snapshots/${encodeURIComponent(snapshotId)}/map-features?simplify=true`,
    { signal },
  );
}

export async function submitFacilityPopulation(body: {
  org_unit_id: string;
  year: number;
  population: number;
  source_name: string;
  reason?: string;
}): Promise<{ id: string; status: string; year: number }> {
  return api("/populations/facility", {
    method: "POST",
    body: JSON.stringify({
      ...body,
      population_type: "facility_catchment_estimate",
    }),
  });
}

export async function askAi(
  task: "findings" | "explain" | "ask" | "report",
  body: {
    org_unit_id: string;
    period: string;
    module?: string;
    comparison_period?: string;
    question?: string;
    indicator_code?: string;
    analysis_snapshot_id?: string;
    view_hash?: string;
  },
): Promise<AiResponse> {
  return api<AiResponse>(`/ai/${task}`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function getExportJob(jobId: string): Promise<{
  job_id: string;
  status: string;
  downloadable: boolean;
  message?: string;
}> {
  return api(`/exports/jobs/${jobId}`);
}

export async function waitForExport(jobId: string): Promise<void> {
  for (let attempt = 0; attempt < 40; attempt += 1) {
    const job = await getExportJob(jobId);
    if (job.status === "failed") {
      throw new Error("Export job failed.");
    }
    if (job.downloadable) {
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 400));
  }
  throw new Error("Export job did not become downloadable.");
}

export async function requestExport(
  kind: string,
  body: {
    org_unit_id: string;
    period: string;
    module?: string;
    comparison_period?: string;
    analysis_snapshot_id?: string;
    view_hash?: string;
  },
): Promise<{ job_id: string; status: string; message: string }> {
  const path = kind === "excel" ? "/exports/excel" : kind === "powerpoint" ? "/exports/powerpoint" : "/exports/report";
  return api(path, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function downloadExportFile(jobId: string): Promise<void> {
  // Downloads write an access audit record, so they are CSRF-protected POSTs.
  const headers: Record<string, string> = {};
  const csrf = csrfToken();
  if (csrf) {
    headers["X-CSRF-Token"] = csrf;
  }
  const response = await fetch(`${API_BASE}/exports/jobs/${encodeURIComponent(jobId)}/download`, {
    method: "POST",
    credentials: "include",
    headers,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body?.detail?.message ?? "Export download failed.");
  }
  const blob = await response.blob();
  const header = response.headers.get("content-disposition") ?? "";
  const match = header.match(/filename="?([^"]+)"?/i);
  const filename = match?.[1] ?? `export-${jobId}`;
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

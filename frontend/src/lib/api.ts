import type {
  AiResponse,
  CurrentContext,
  DashboardQuery,
  DashboardResponse,
  MapFeatureCollection,
  OpsStatus,
  OrgUnitSummary,
  SyncJob,
} from "./types";

export type { CurrentContext, OrgUnitSummary };

/**
 * Always same-origin: the browser calls `/api/...` on the frontend host and the server-side
 * route `src/app/api/[...path]/route.ts` forwards it to the backend. Session and CSRF cookies
 * therefore belong to the origin the page was served from, which is what makes cookie-only
 * authentication work when the API runs on a private Render service. No backend address is
 * ever compiled into client JavaScript.
 */
const API_BASE = "/api";
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
  const known = ["excel", "powerpoint", "report", "pdf", "word"];
  if (!known.includes(kind)) {
    throw new Error(`Unsupported export type: ${kind}`);
  }
  const path = `/exports/${kind}`;
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
  // transport=blob: raw bytes, so the browser's PDF handler cannot intercept the response.
  const response = await fetch(`${API_BASE}/exports/jobs/${encodeURIComponent(jobId)}/download?transport=blob`, {
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
  const filename = response.headers.get("x-export-filename") ?? match?.[1] ?? `export-${jobId}`;
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.rel = "noopener";
  document.body.appendChild(link);
  link.click();
  link.remove();
  // Browsers start some downloads (notably PDF) after click() returns; revoking the object URL
  // at once hands them an empty file.
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

export async function listExportJobs(limit = 20): Promise<{ jobs: import("./types").ExportJobSummary[] }> {
  return api(`/exports/jobs?limit=${limit}`);
}

export async function retryExportJob(jobId: string): Promise<{ job_id: string; status: string; message: string }> {
  return api(`/exports/jobs/${encodeURIComponent(jobId)}/retry`, { method: "POST" });
}

export type SearchResults = {
  query: string;
  org_units: Array<{ id: string; code: string; name: string; level_type: string }>;
  indicators: Array<{ code: string; name: string; programme: string; module: string }>;
};

/** Authorised search. The server restricts results to the caller's geography and programmes. */
export async function searchAuthorised(query: string, signal?: AbortSignal): Promise<SearchResults> {
  return api<SearchResults>(`/search?q=${encodeURIComponent(query)}`, { signal });
}

/** Ask the server to select the one complete, in-force mapping and refresh the dashboard source. */
export async function refreshDashboardSource(body: {
  org_unit_id: string;
  period: string;
  module: string;
  idempotency_key: string;
}): Promise<SyncJob> {
  return api<SyncJob>("/sync/refresh", { method: "POST", body: JSON.stringify(body) });
}

export async function getSyncJob(jobId: string): Promise<SyncJob> {
  return api<SyncJob>(`/sync/jobs/${encodeURIComponent(jobId)}`);
}

export async function getOpsStatus(): Promise<OpsStatus> {
  return api<OpsStatus>("/ops/status");
}

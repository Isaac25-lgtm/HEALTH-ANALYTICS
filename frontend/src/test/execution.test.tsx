import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { KpiCard } from "@/components/ui/KpiCard";
import {
  downloadExportFile,
  getAnalysisSnapshot,
  getSnapshotMapFeatures,
  newRequestKey,
  queryDashboard,
} from "@/lib/api";
import { dashboardHref, snapshotAnswersRequest } from "@/lib/scope";
import { interpretationLabel, mapStateCopy } from "@/lib/status";
import type { Measure } from "@/lib/types";

function jsonResponse(body: unknown, init: ResponseInit = {}) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
    ...init,
  });
}

describe("analytical execution contract", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    document.cookie = "hpip_csrf=csrf-test-token";
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    document.cookie = "hpip_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
  });

  it("executes a dashboard through a CSRF-protected POST with an idempotency key", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ analysis_snapshot_id: "snap-1" }, { status: 201 }));
    await queryDashboard({
      orgUnitId: "org-1",
      period: "FY2024/25",
      module: "anc",
      comparison: "FY2023/24",
      indicator: "ANC1_COVERAGE",
      requestKey: "request-key-0001",
    });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/analytics\/dashboard\/query$/);
    expect(init.method).toBe("POST");
    expect(init.headers["X-CSRF-Token"]).toBe("csrf-test-token");
    expect(JSON.parse(init.body)).toEqual({
      org_unit_id: "org-1",
      period: "FY2024/25",
      module: "anc",
      comparison_period: "FY2023/24",
      selected_indicator: "ANC1_COVERAGE",
      request_key: "request-key-0001",
    });
  });

  it("re-opens committed snapshots and map features with read-only GETs", async () => {
    fetchMock.mockImplementation(() => Promise.resolve(jsonResponse({})));
    await getAnalysisSnapshot("snap-1");
    await getSnapshotMapFeatures("snap-1");
    const [snapshotUrl, snapshotInit] = fetchMock.mock.calls[0];
    const [mapUrl, mapInit] = fetchMock.mock.calls[1];
    expect(snapshotUrl).toMatch(/\/analysis-snapshots\/snap-1$/);
    expect(mapUrl).toMatch(/\/analysis-snapshots\/snap-1\/map-features\?simplify=true$/);
    for (const init of [snapshotInit, mapInit]) {
      expect(init.method ?? "GET").toBe("GET");
      expect(init.body).toBeUndefined();
      expect(init.headers["X-CSRF-Token"]).toBeUndefined();
    }
  });

  it("downloads exports through a CSRF-protected POST", async () => {
    fetchMock.mockResolvedValue(
      new Response("file", { status: 200, headers: { "content-disposition": 'attachment; filename="job.md"' } }),
    );
    const createObjectURL = vi.fn(() => "blob:test");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL, revokeObjectURL }));
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    await downloadExportFile("job-1");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/exports\/jobs\/job-1\/download$/);
    expect(init.method).toBe("POST");
    expect(init.headers["X-CSRF-Token"]).toBe("csrf-test-token");
    expect(click).toHaveBeenCalled();
    click.mockRestore();
  });

  it("generates request keys the API accepts", () => {
    const key = newRequestKey();
    expect(key).toMatch(/^[A-Za-z0-9_-]{8,80}$/);
    expect(newRequestKey()).not.toBe(key);
  });

  it("keeps request and snapshot identity in the URL so refresh never recalculates", () => {
    const href = dashboardHref({
      screen: "regional",
      orgUnitId: "org-1",
      period: "FY2024/25",
      module: "anc",
      request: "request-key-0001",
      snapshot: "snap-1",
    });
    expect(href).toContain("/dashboard/regional");
    expect(href).toContain("request=request-key-0001");
    expect(href).toContain("snapshot=snap-1");
    expect(dashboardHref({ workspace: "mpdsr", period: "FY2024/25" })).toMatch(/^\/workspace\/mpdsr\?/);
  });

  it("reuses a snapshot only when it answers the URL request", () => {
    const snapshot = { scope: { id: "org-1" }, period: "FY2024/25", module: "anc" };
    expect(snapshotAnswersRequest(snapshot, { orgUnitId: "org-1", period: "FY2024/25", module: "anc" })).toBe(true);
    expect(snapshotAnswersRequest(snapshot, { period: "FY2024/25" })).toBe(true);
    expect(snapshotAnswersRequest(snapshot, { orgUnitId: "org-2", period: "FY2024/25" })).toBe(false);
    expect(snapshotAnswersRequest(snapshot, { period: "FY2023/24" })).toBe(false);
    expect(snapshotAnswersRequest(snapshot, { period: "FY2024/25", module: "mpdsr" })).toBe(false);
  });
});

describe("direction-aware presentation", () => {
  const base: Measure = {
    indicator_code: "TEENAGE_PREGNANCY",
    name: "Teenage pregnancy",
    raw_value: 10,
    display_value: "10.0",
    numerator: 1000,
    denominator: 10000,
    unit: "%",
    status: "yellow",
  };

  it("labels change from the server interpretation, never from the sign", () => {
    render(
      <KpiCard
        measure={{
          ...base,
          change: {
            change_kind: "percentage_point",
            percentage_point_change: -10,
            relative_percent_change: -50,
            absolute_change: -10,
            interpretation: "improved",
          },
        }}
      />,
    );
    expect(screen.getByText("-10.0 pp")).toBeInTheDocument();
    expect(screen.getByText(/Improved/)).toBeInTheDocument();
  });

  it("does not call BLUE or unclassified movement better or worse", () => {
    // No approved direction rule: no label at all, never "better" or "worse".
    expect(interpretationLabel({ interpretation: "not_interpreted" })).toBeNull();
    expect(interpretationLabel({ interpretation: "deteriorated" })).toBe("Deteriorated");
    expect(interpretationLabel(null)).toBeNull();
  });

  it("explains unavailable map levels without substituting other boundaries", () => {
    expect(mapStateCopy("mapped")).toBeNull();
    const copy = mapStateCopy("geometry_unavailable_for_level");
    expect(copy?.title).toBe("Boundaries unavailable for this level");
    expect(copy?.detail).toContain("not substituted");
    expect(mapStateCopy("mixed_levels_not_mapped", "Server note")?.detail).toBe("Server note");
  });
});

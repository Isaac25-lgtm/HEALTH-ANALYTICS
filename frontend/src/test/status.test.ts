import { describe, expect, it } from "vitest";
import { changeLabel, formatMeasure, resolveStatus, statusMeta } from "@/lib/status";
import { dashboardHref, screenForLevel } from "@/lib/scope";

describe("status and units", () => {
  it("keeps missing distinct from zero", () => {
    expect(resolveStatus({ raw_value: null, status: "n_a" })).toBe("missing");
    expect(resolveStatus({ raw_value: 0, status: "green" })).toBe("green");
    expect(formatMeasure(null, "%")).toBe("No data");
    expect(formatMeasure(0, "%", "0.0")).toBe("0.0");
  });

  it("does not treat BLUE as high performance", () => {
    const meta = statusMeta(resolveStatus({ raw_value: 101.9, status: "blue", quality_status: "blue" }));
    expect(meta.label).toBe("Non-assessable");
    expect(meta.cue).toBe("B");
  });

  it("retains values above 100 percent", () => {
    expect(formatMeasure(181.3, "%", "181.3")).toContain("181.3");
  });

  it("keeps rates from being shown as bare percentages", () => {
    expect(formatMeasure(28.4, "per 1,000 deliveries", "28.4")).toContain("per 1,000");
  });

  it("labels percentage-point change separately from relative change", () => {
    expect(
      changeLabel({
        change_kind: "percentage_point",
        percentage_point_change: -2,
        relative_percent_change: -2.05,
      }),
    ).toBe("-2.0 pp");
  });
});

describe("dashboard scope", () => {
  it("maps levels to the four mandatory screens", () => {
    expect(screenForLevel("country")).toBe("national");
    expect(screenForLevel("sub_region")).toBe("regional");
    expect(screenForLevel("district")).toBe("district");
    expect(screenForLevel("facility")).toBe("facility");
  });

  it("preserves selected geography in the URL without inventing authority", () => {
    const href = dashboardHref({
      screen: "regional",
      orgUnitId: "abc",
      period: "FY2024/25",
      module: "anc",
    });
    expect(href).toContain("/dashboard/regional");
    expect(href).toContain("orgUnitId=abc");
    expect(href).toContain("module=anc");
  });
});

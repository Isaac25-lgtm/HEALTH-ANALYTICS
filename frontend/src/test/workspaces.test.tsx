import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { KpiCard } from "@/components/ui/KpiCard";
import { unavailableLabel } from "@/lib/status";
import { WORKSPACES, moduleFor, sectionsFor } from "@/lib/workspaces";
import type { Measure } from "@/lib/types";

describe("workspace compositions", () => {
  it("defines every specialised workspace required by the owner", () => {
    expect(Object.keys(WORKSPACES).sort()).toEqual(
      ["admin", "ai", "anc", "immunization", "intrapartum", "maps", "mpdsr", "quality", "reports", "trends"].sort(),
    );
  });

  it("gives workspaces genuinely different surfaces", () => {
    expect(sectionsFor("maps")).toContain("map");
    expect(sectionsFor("maps")).not.toContain("exports");
    expect(sectionsFor("reports")).toEqual(["exports", "exportHistory"]);
    expect(sectionsFor("quality")).toContain("quality");
    expect(sectionsFor("mpdsr")).toContain("mpdsr");
    expect(sectionsFor("immunization")).toContain("continuum");
    expect(sectionsFor("admin")).toContain("administration");
  });

  it("falls back to the full geography composition without a workspace", () => {
    const sections = sectionsFor(undefined);
    for (const key of ["kpis", "map", "scorecard", "trend", "exports"]) {
      expect(sections).toContain(key);
    }
    expect(sectionsFor("unknown-workspace")).toEqual(sections);
  });

  it("pins only programme workspaces to a module", () => {
    expect(moduleFor("anc")).toBe("anc");
    expect(moduleFor("mpdsr")).toBe("mpdsr");
    expect(moduleFor("maps")).toBeUndefined();
    expect(moduleFor("reports")).toBeUndefined();
  });
});

describe("unavailable states", () => {
  it("names a missing population denominator in plain words", () => {
    expect(unavailableLabel("population_unavailable")).toBe("Population denominator unavailable");
    expect(unavailableLabel("population_denominator_unavailable")).toBe("Population denominator unavailable");
    expect(unavailableLabel("formula_version_unavailable")).toBe("No formula version valid for this period");
    expect(unavailableLabel(null)).toBe("No calculated value");
  });

  it("never renders a missing value as zero", () => {
    const measure = {
      indicator_code: "ANC1_COVERAGE",
      name: "ANC1 coverage",
      raw_value: null,
      display_value: null,
      numerator: 120,
      denominator: null,
      unit: "%",
      status: "n_a",
      performance_status: "n_a",
      quality_status: "blue",
      reason_code: "population_unavailable",
    } as unknown as Measure;
    render(<KpiCard measure={measure} />);
    expect(screen.getByText("Population denominator unavailable")).toBeInTheDocument();
    expect(screen.getByText("No data")).toBeInTheDocument();
    expect(screen.queryByText("0")).not.toBeInTheDocument();
    expect(screen.queryByText("0%")).not.toBeInTheDocument();
  });
});

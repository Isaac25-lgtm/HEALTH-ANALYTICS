import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { KpiCard } from "@/components/ui/KpiCard";
import { COMPOSITIONS } from "@/components/workspaces/registry";
import type { CompositionProps } from "@/components/workspaces/types";
import { unavailableLabel } from "@/lib/status";
import { WORKSPACES, compositionFor, moduleFor } from "@/lib/workspaces";
import type { Measure } from "@/lib/types";
import { fixtureContext, fixtureDashboard } from "./fixtures";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }) }));

function renderComposition(key: keyof typeof COMPOSITIONS, overrides: Partial<CompositionProps> = {}) {
  const Composition = COMPOSITIONS[key];
  return render(
    <Composition
      dashboard={fixtureDashboard()}
      context={fixtureContext()}
      screen="regional"
      onOpenEvidence={() => undefined}
      hrefFor={(target) => `/test/${target.workspace ?? target.screen ?? "same"}/${target.orgUnitId ?? ""}`}
      {...overrides}
    />,
  );
}

function headings(container: HTMLElement): string[] {
  return within(container)
    .getAllByRole("heading", { level: 2 })
    .map((node) => node.textContent ?? "");
}

describe("workspace registry", () => {
  it("defines every specialised workspace required by the owner", () => {
    expect(Object.keys(WORKSPACES).sort()).toEqual(
      ["admin", "ai", "anc", "immunization", "intrapartum", "maps", "mpdsr", "quality", "reports", "trends"].sort(),
    );
  });

  it("maps every workspace and screen family to its own composition component", () => {
    const components = new Set(Object.values(COMPOSITIONS));
    expect(components.size).toBe(Object.keys(COMPOSITIONS).length);
    for (const spec of Object.values(WORKSPACES)) {
      expect(COMPOSITIONS[spec.composition]).toBeDefined();
      expect(compositionFor("national", spec.slug)).toBe(spec.composition);
    }
    expect(compositionFor("facility")).toBe("facility");
    expect(compositionFor("regional")).toBe("geography");
    expect(compositionFor("regional", "unknown-workspace")).toBe("geography");
  });

  it("pins only programme workspaces to a module", () => {
    expect(moduleFor("anc")).toBe("anc");
    expect(moduleFor("mpdsr")).toBe("mpdsr");
    expect(moduleFor("maps")).toBeUndefined();
    expect(moduleFor("reports")).toBeUndefined();
  });
});

describe("compositions render genuinely different panel sets", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify({ jobs: [] }), { status: 200 }))));
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("national/regional overview: map, insights, unit scorecard, trend, ranking, ask and downloads", () => {
    const { container } = renderComposition("geography");
    expect(headings(container)).toEqual([
      "Geographic intelligence",
      "Priority insights",
      "Unit scorecard",
      "Trends",
      "Top and bottom performers",
      "Ask the Data",
      "Downloads",
    ]);
  });

  it("district view leads with the facility scorecard and has no map", () => {
    const { container } = renderComposition("geography", { screen: "district" });
    const names = headings(container);
    expect(names[0]).toBe("Facility performance scorecard");
    expect(names).not.toContain("Geographic intelligence");
  });

  it.each([
    ["facility", ["Indicator scorecard", "Facility trends", "Data quality issues", "Catchment population", "Ask the Data", "Downloads"]],
    ["anc", ["ANC indicator scorecard", "ANC coverage by unit", "Priority insights", "ANC trends", "Top and bottom performers", "Downloads"]],
    ["intrapartum", ["Intrapartum and newborn scorecard", "Delivery and outcome trends", "Priority insights", "Performance by unit", "Data quality issues", "Downloads"]],
    ["immunization", ["Immunisation continuum", "Antigen coverage by unit", "Priority insights", "Coverage trends", "Top and bottom performers", "Downloads"]],
    ["mpdsr", ["Notification and review scorecard", "Cause patterns and reviews", "MPDSR process trends", "Data quality issues", "Key learning", "Downloads"]],
    ["maps", ["Geographic intelligence", "Top and bottom performers", "Mapped unit values"]],
    ["trends", ["Indicator trends", "Top and bottom performers", "Current values by unit", "Priority insights"]],
    ["quality", ["Data-quality console", "Why some indicators have no value", "All priority insights", "Indicator status"]],
    ["reports", ["Downloads", "Recent export jobs"]],
    ["ai", ["Ask the Data", "Priority insights"]],
    ["admin", ["Administration"]],
  ] as const)("%s composition", (key, expected) => {
    const { container } = renderComposition(key);
    expect(headings(container)).toEqual(expected);
  });

  it("shows a short prioritised insight list with a view-all path instead of every flag", () => {
    renderComposition("geography");
    const items = screen.getAllByText(/^Fixture insight/);
    expect(items).toHaveLength(4);
    expect(items[0]).toHaveTextContent("Fixture insight 5");
    expect(screen.getByRole("link", { name: /View all 9 insights and 12 quality flags/ })).toHaveAttribute(
      "href",
      "/test/quality",
    );
    expect(screen.queryByText("Fixture flag 11")).not.toBeInTheDocument();
  });

  it("paginates quality flags", () => {
    renderComposition("quality");
    expect(screen.getByText("Fixture flag 0")).toBeInTheDocument();
    expect(screen.queryByText("Fixture flag 8")).not.toBeInTheDocument();
    expect(screen.getByText("Page 1 of 2")).toBeInTheDocument();
  });

  it("limits the KPI strip to six cards and keeps missing values unavailable, never zero", () => {
    renderComposition("geography");
    const strip = screen.getByRole("region", { name: "Key indicators" });
    expect(within(strip).getAllByRole("article")).toHaveLength(6);
    expect(within(strip).getByText("Population denominator unavailable")).toBeInTheDocument();
    expect(within(strip).queryByText("0")).not.toBeInTheDocument();
    expect(within(strip).queryByText("0%")).not.toBeInTheDocument();
  });

  it("keeps a map-less scope inside the map panel instead of collapsing the layout", () => {
    renderComposition("geography");
    expect(screen.getByText("Boundaries unavailable for this level")).toBeInTheDocument();
  });

  it("withholds MPDSR causes with the server's reason", () => {
    renderComposition("mpdsr");
    expect(screen.getByText("Cause patterns withheld")).toBeInTheDocument();
    expect(screen.getByText(/No approved MPDSR cause taxonomy/)).toBeInTheDocument();
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
    const missing = {
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
    render(<KpiCard measure={missing} />);
    expect(screen.getByText("Population denominator unavailable")).toBeInTheDocument();
    expect(screen.getByText("No data")).toBeInTheDocument();
    expect(screen.queryByText("0")).not.toBeInTheDocument();
    expect(screen.queryByText("0%")).not.toBeInTheDocument();
  });
});

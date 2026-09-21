import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AppShell } from "@/components/shell/AppShell";
import {
  financialYearOptions,
  latestClosedFinancialYear,
  periodOptionLabel,
  previousFinancialYear,
} from "@/lib/scope";
import { fixtureContext, fixtureDashboard } from "./fixtures";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
}));

describe("safe period defaults", () => {
  it("chooses the latest closed Uganda financial year", () => {
    const asOf = new Date(2026, 8, 20);
    expect(latestClosedFinancialYear(asOf)).toBe("FY2025/26");
    expect(previousFinancialYear("FY2025/26")).toBe("FY2024/25");
    expect(periodOptionLabel("FY2026/27", asOf)).toContain("in progress");
    expect(financialYearOptions(new Date(2030, 8, 20))).toEqual([
      "FY2028/29",
      "FY2029/30",
      "FY2030/31",
    ]);
  });
});

describe("capability-aware navigation", () => {
  it("shows only reachable geographies and authorised programme workspaces", () => {
    const country = {
      id: "ug",
      code: "UG",
      name: "Uganda",
      level_type: "country",
      parent_id: null,
      path: "/UG",
    };
    render(
      <AppShell
        context={fixtureContext({
          landing_org_unit: country,
          geography_entry_units: [country],
          available_geography_levels: ["country"],
          programmes: ["MNCH"],
          actions: ["view", "export"],
        })}
        dashboard={fixtureDashboard({ scope: { ...fixtureDashboard().scope, ...country } })}
        screen="national"
      >
        <p>Content</p>
      </AppShell>,
    );
    expect(screen.getByRole("link", { name: /National/ })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Regional/ })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /ANC and MNCH/ })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Immunisation/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /^MPDSR$/ })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Reports and exports/i })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /AI Insights/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Administration/ })).not.toBeInTheDocument();
  });
});

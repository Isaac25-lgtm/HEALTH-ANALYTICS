import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { KpiCard } from "@/components/ui/KpiCard";
import { IndicatorTable } from "@/components/panels/ScorecardPanels";
import { StatusPill } from "@/components/ui/StatusPill";
import type { Measure } from "@/lib/types";

const base: Measure = {
  indicator_code: "ANC1_COVERAGE",
  name: "ANC1 coverage",
  raw_value: 95.4,
  display_value: "95.4",
  numerator: 47700,
  denominator: 50000,
  unit: "%",
  status: "green",
};

describe("dashboard presentation", () => {
  it("renders KPI units and accessible status text", () => {
    render(<KpiCard measure={base} />);
    // Percentages read as "95.4%", as on the reference screens.
    expect(screen.getByText("95.4%")).toBeInTheDocument();
    expect(screen.getByText("On track")).toBeInTheDocument();
  });

  it("shows genuine zero and missing states differently", () => {
    render(<StatusPill status="missing" />);
    expect(screen.getByText("No data")).toBeInTheDocument();
    render(
      <IndicatorTable
        rows={[
          { ...base, raw_value: 0, display_value: "0.0", status: "red", indicator_code: "ZERO" },
          { ...base, raw_value: null, display_value: null, status: "n_a", indicator_code: "MISSING" },
        ]}
        onOpen={() => undefined}
      />,
    );
    expect(screen.getByText("0.0%")).toBeInTheDocument();
    expect(screen.getAllByText("No data").length).toBeGreaterThan(0);
  });
});

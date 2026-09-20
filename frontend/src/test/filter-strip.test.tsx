import { cleanup, fireEvent, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FilterStrip } from "@/components/dashboard/DashboardFrame";
import { fixtureContext, fixtureDashboard } from "./fixtures";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }) }));

/**
 * The indicator list on screen belongs to the module on screen. Submitting one module's indicator
 * code with a different module asks the server for a pair it must reject (HTTP 422), which left the
 * dashboard with no panels at all.
 */
describe("filter strip module and indicator stay consistent", () => {
  const dashboard = fixtureDashboard();

  afterEach(cleanup);

  it("drops the previous module's indicator when the module changes", () => {
    const onApply = vi.fn();
    const view = render(
      <FilterStrip
        dashboard={dashboard}
        context={fixtureContext()}
        geographyOptions={[]}
        comparison={dashboard.comparison_period ?? undefined}
        onApply={onApply}
      />,
    );

    fireEvent.change(view.getByLabelText("Programme module"), { target: { value: "mpdsr" } });
    fireEvent.click(view.getByRole("button", { name: "Apply" }));

    expect(onApply).toHaveBeenCalledTimes(1);
    expect(onApply.mock.calls[0][0]).toMatchObject({ module: "mpdsr", indicator: "" });
  });

  it("keeps the selected indicator while the module is unchanged", () => {
    const onApply = vi.fn();
    const view = render(
      <FilterStrip
        dashboard={dashboard}
        context={fixtureContext()}
        geographyOptions={[]}
        comparison={dashboard.comparison_period ?? undefined}
        onApply={onApply}
      />,
    );

    fireEvent.click(view.getByRole("button", { name: "Apply" }));

    const applied = onApply.mock.calls[0][0];
    expect(applied.module).toBe(dashboard.module);
    expect(applied.indicator).toBe(dashboard.selected_indicator ?? dashboard.ranking.indicator_code);
  });
});

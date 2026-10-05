import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import LoginPage from "@/app/login/page";
import { clearReadyDashboard, readReadyDashboard } from "@/lib/dashboard-ready";
import { fixtureContext, fixtureDashboard } from "./fixtures";

const mocks = vi.hoisted(() => ({
  replace: vi.fn(), login: vi.fn(), context: vi.fn(), prepared: vi.fn(), query: vi.fn(), children: vi.fn(),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: mocks.replace }) }));
vi.mock("@/lib/api", async (original) => ({
  ...await original<typeof import("@/lib/api")>(),
  login: mocks.login, getContext: mocks.context, getPreparedDashboard: mocks.prepared,
  queryDashboard: mocks.query, getChildren: mocks.children,
}));

describe("sign-in opens only a ready, authorised dashboard", () => {
  const dashboard = fixtureDashboard();
  const context = fixtureContext({ landing_org_unit: dashboard.scope });
  beforeEach(() => {
    vi.clearAllMocks();
    clearReadyDashboard();
    mocks.login.mockResolvedValue({ ok: true, csrf_token: "test-only-csrf" });
    mocks.context.mockResolvedValue(context);
    mocks.children.mockResolvedValue([]);
    mocks.prepared.mockResolvedValue(null);
  });
  afterEach(() => { cleanup(); clearReadyDashboard(); });

  function submit() {
    render(<LoginPage />);
    fireEvent.change(screen.getByLabelText("Username"), { target: { value: "test-only-user" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "test-only-password" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
  }

  it("shows the verified name, role and geography while preparation is pending", async () => {
    let finish!: (value: typeof dashboard) => void;
    mocks.query.mockReturnValue(new Promise((resolve) => { finish = resolve; }));
    submit();
    await screen.findByText(context.display_name);
    expect(screen.getByRole("status").textContent).toContain("Regional Analyst");
    expect(screen.getByRole("status").textContent).toContain(context.landing_org_unit!.name);
    expect(mocks.replace).not.toHaveBeenCalled();
    finish(dashboard);
    await waitFor(() => expect(mocks.replace).toHaveBeenCalledTimes(1));
    expect(mocks.replace.mock.calls[0][0]).toContain(`snapshot=${dashboard.analysis_snapshot_id}`);
    expect(readReadyDashboard(dashboard.analysis_snapshot_id)?.dashboard).toBe(dashboard);
  });

  it("uses a ready product instead of recalculating on sign-in", async () => {
    mocks.prepared.mockResolvedValue(dashboard);
    submit();
    await waitFor(() => expect(mocks.replace).toHaveBeenCalledTimes(1));
    expect(mocks.query).not.toHaveBeenCalled();
  });

  it("does not enter an empty dashboard merely because snapshot preparation finished", async () => {
    mocks.prepared.mockResolvedValue({ ...dashboard, module_result: { ...dashboard.module_result, indicators: [] } });
    submit();
    await screen.findByText(/No governed source-backed indicator values/);
    expect(mocks.replace).not.toHaveBeenCalled();
    expect(mocks.children).not.toHaveBeenCalled();
  });

  it("stays on sign-in after a preparation failure and retries without authenticating twice", async () => {
    mocks.query.mockRejectedValueOnce(new Error("Preparation unavailable")).mockResolvedValueOnce(dashboard);
    submit();
    await screen.findByText("Preparation unavailable");
    expect(mocks.replace).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Retry dashboard preparation" }));
    await waitFor(() => expect(mocks.replace).toHaveBeenCalledTimes(1));
    expect(mocks.login).toHaveBeenCalledTimes(1);
  });
});

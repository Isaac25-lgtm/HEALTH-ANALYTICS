import { defineConfig, devices } from "@playwright/test";

// CI supplies `python`; Windows developers can point this at their chosen interpreter.
// Do not hard-code a workstation path into the test contract.
const python = process.env.HPIP_PYTHON ?? "python";
const pythonCommand = `"${python.replaceAll('"', '\\"')}"`;
const browserExecutable = process.env.HPIP_BROWSER_EXECUTABLE;
// Reuse is opt-in. Leaving it on for every local run can strand the disposable
// API/Next processes after Playwright completes.
const reuseExistingServer = process.env.HPIP_REUSE_E2E_SERVER === "true";
// The acceptance gate owns both servers directly so it can stop the exact child processes without
// Playwright's shell-based Windows teardown. Direct `playwright test` keeps the convenient built-in
// web-server lifecycle.
const externalServers = process.env.HPIP_E2E_EXTERNAL_SERVERS === "true";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  // One disposable SQLite API serves every worker, and each screen commits a real calculation
  // snapshot. Two workers keep that queue honest; more of them measure contention, not the product.
  workers: 2,
  retries: 0,
  timeout: 60_000,
  use: {
    baseURL: "http://localhost:3000",
    trace: "off",
  },
  reporter: [["list"], ["json", { outputFile: "playwright-report/results.json" }]],
  webServer: externalServers
    ? []
    : [
        {
          command: `${pythonCommand} scripts/run_e2e_api.py`,
          cwd: "../backend",
          url: "http://127.0.0.1:8010/health",
          reuseExistingServer,
          timeout: 120_000,
        },
        {
          // Same-origin proxy, exactly as deployed: a production build made without any backend
          // address, then `next start` with the backend given only at runtime in Render's bare
          // host:port form. The browser calls /api on port 3000.
          command: "node scripts/e2e-web.mjs",
          url: "http://localhost:3000",
          reuseExistingServer,
          timeout: 240_000,
          env: {
            E2E_BACKEND_HOSTPORT: "127.0.0.1:8010",
          },
        },
      ],
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        launchOptions: {
          // Leave this unset in CI so Playwright uses its managed Chromium.
          ...(browserExecutable ? { executablePath: browserExecutable } : {}),
          args: ["--headless=new", "--disable-gpu"],
        },
      },
    },
  ],
});

#!/usr/bin/env node
/**
 * Bounded acceptance runner for the Playwright suite.
 *
 * The gate owns the production build, the disposable API, the Next server and Playwright as direct
 * children. Playwright's built-in webServer launcher necessarily inserts command shells; on
 * restricted Windows accounts its taskkill-based teardown can be denied and wait forever. Removing
 * that shell-owned lifecycle gives this process exact handles that it can stop and await.
 *
 * The run fails unless every test passes without skips, Playwright exits by itself, the owned
 * services close, ports 3000/8010 are free, no process created during the run remains, the JSON
 * report is fresh, and the working tree's status and content fingerprint are unchanged by the run
 * (a pre-existing dirty tree is permitted). Post-summary, pre-summary inactivity, overall, build,
 * service-stop and process-query bounds independently prevent silent hangs. Lifecycle logic and
 * its tests live in `e2e-gate-lib.mjs` / `e2e-gate-lib.test.mjs`.
 */
import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { boundsFromEnv, createProcessTable, createTreeStateReader, runGate } from "./e2e-gate-lib.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repo = path.resolve(root, "..");
const nextBin = path.join(root, "node_modules", "next", "dist", "bin", "next");
const cli = path.join(root, "node_modules", "@playwright", "test", "cli.js");
const backendHostPort = process.env.E2E_BACKEND_HOSTPORT ?? "127.0.0.1:8010";
const evidenceRefresh = process.env.UPDATE_VISUAL_EVIDENCE === "1";
const bounds = boundsFromEnv(process.env);

const buildEnv = { ...process.env, NODE_ENV: "production" };
delete buildEnv.BACKEND_INTERNAL_URL;
delete buildEnv.NEXT_PUBLIC_API_BASE_URL;

const { summary, exitCode } = await runGate({
  ports: [3000, 8010],
  reportPath: path.join(root, "playwright-report", "results.json"),
  noSkipsScript: path.join(root, "scripts", "assert-no-skips.mjs"),
  bounds,
  processTable: createProcessTable({ timeoutMs: bounds.processQueryTimeoutMs }),
  readTreeState: createTreeStateReader({ repo, evidenceRefresh }),
  evidenceRefresh,
  prepareBuild: () => spawnSync(process.execPath, [path.join(root, "scripts", "prepare-build-dir.mjs")], { cwd: root, stdio: "inherit" }),
  build: {
    label: "e2e-build",
    executable: process.execPath,
    args: [nextBin, "build"],
    options: { cwd: root, env: buildEnv },
  },
  backend: {
    label: "e2e-api",
    executable: process.env.HPIP_PYTHON ?? "python",
    args: ["scripts/run_e2e_api.py"],
    options: { cwd: path.join(repo, "backend"), env: process.env },
    readyUrl: "http://127.0.0.1:8010/health",
    readyTimeoutMs: 120_000,
  },
  web: {
    label: "e2e-web",
    executable: process.execPath,
    args: [nextBin, "start", "--port", "3000"],
    options: { cwd: root, env: { ...process.env, NODE_ENV: "production", BACKEND_INTERNAL_URL: backendHostPort } },
    readyUrl: "http://127.0.0.1:3000",
    readyTimeoutMs: 60_000,
  },
  playwright: {
    label: "playwright",
    executable: process.execPath,
    args: [cli, "test", ...process.argv.slice(2)],
    options: { cwd: root, env: { ...process.env, HPIP_E2E_EXTERNAL_SERVERS: "true" } },
  },
});

console.log(`\n[e2e-gate] ${JSON.stringify(summary, null, 2)}`);
process.exit(exitCode);

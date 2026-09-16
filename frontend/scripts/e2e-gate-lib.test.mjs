// @vitest-environment node
/**
 * Deterministic tests for the acceptance gate's lifecycle and process attribution.
 *
 * Synthetic tables prove the attribution rules exactly. The runGate cases use real child processes
 * (Node scripts standing in for the build, API, Next server and Playwright) with the real process
 * table, so spawn failure, bounded cleanup and survivor termination are exercised, not simulated.
 */
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { afterAll, describe, expect, it } from "vitest";
import {
  captureIdentity,
  createProcessTable,
  defaultProcessCommands,
  delay,
  descendantsOf,
  findSurvivors,
  listProcesses,
  parseUnixRows,
  processKey,
  recordObservations,
  runGate,
  sameProcess,
  startOwnedProcess,
  stopOwnedProcess,
  terminateVerifiedSurvivors,
} from "./e2e-gate-lib.mjs";

const cim = (ms) => `/Date(${ms})/`;
const row = (pid, ppid, ms, name = `p${pid}`) => ({ pid, ppid, name, created: cim(ms) });
const names = (rows) => rows.map((item) => item.name);
const silent = { stdout: () => {}, stderr: () => {} };
const noSkipsScript = fileURLToPath(new URL("./assert-no-skips.mjs", import.meta.url));
const scratch = mkdtempSync(path.join(os.tmpdir(), "hpip-gate-test-"));
const strayPids = new Set();

function isAlive(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return error.code === "EPERM";
  }
}

async function waitUntilDead(pid, milliseconds = 10_000) {
  const deadline = Date.now() + milliseconds;
  while (Date.now() < deadline) {
    if (!isAlive(pid)) return true;
    await delay(100);
  }
  return !isAlive(pid);
}

afterAll(() => {
  // Only processes these tests started themselves are recorded here.
  for (const pid of strayPids) {
    try {
      process.kill(pid, "SIGKILL");
    } catch {
      // already gone
    }
  }
  rmSync(scratch, { recursive: true, force: true });
});

describe("descendant attribution", () => {
  it("attributes nothing when the root PID was reused by another process", () => {
    const rows = [row(100, 1, 9000, "reuser"), row(101, 100, 9500, "reuser-child")];
    const result = descendantsOf(rows, { pid: 100, created: cim(1000) });
    expect(result.rootVerified).toBe(false);
    expect(result.rows).toEqual([]);
  });

  it("rejects a child whose PID belongs to a process older than its supposed parent, with its subtree", () => {
    const rows = [
      row(100, 1, 1000, "root"),
      row(200, 100, 500, "older-unrelated"),
      row(201, 200, 600, "older-unrelated-child"),
      row(300, 100, 2000, "genuine-child"),
      row(301, 300, 2500, "genuine-grandchild"),
    ];
    expect(names(descendantsOf(rows, { pid: 100, created: cim(1000) }).rows)).toEqual(["genuine-child", "genuine-grandchild"]);
  });

  it("terminates on a cyclic parent graph without duplicates", () => {
    const rows = [row(10, 12, 1000, "root"), row(11, 10, 2000, "a"), row(12, 11, 3000, "b")];
    expect(names(descendantsOf(rows, { pid: 10, created: cim(1000) }).rows)).toEqual(["a", "b"]);
  });

  it("accepts equal creation times, rejects unknown ones, and matches identities across formats", () => {
    const rows = [
      row(1, 0, 1000, "root"),
      row(2, 1, 1000, "same-millisecond"),
      { pid: 3, ppid: 1, name: "unknown-time", created: "not a time" },
    ];
    expect(names(descendantsOf(rows, { pid: 1, created: cim(1000) }).rows)).toEqual(["same-millisecond"]);
    expect(sameProcess({ pid: 7, created: "1970-01-01T00:00:01.000Z" }, { pid: 7, created: cim(1000) })).toBe(true);
    expect(sameProcess({ pid: 7, created: cim(1000) }, { pid: 7, created: cim(1500) })).toBe(false);
    expect(sameProcess({ pid: 8, created: cim(1000) }, { pid: 7, created: cim(1000) })).toBe(false);
  });
});

describe("observation and survivor cleanup", () => {
  const verifiedRoot = { label: "playwright", running: true, identity: { pid: 100, created: cim(1000), name: "root" } };

  it("never uses an exited owned process as a root", () => {
    const seen = new Map();
    const table = { rows: [row(100, 1, 1000, "root"), row(300, 100, 2000, "child")] };
    recordObservations({ table, mode: "parent-tree", owned: [{ ...verifiedRoot, running: false }], baselineKeys: new Set(), seen });
    expect(seen.size).toBe(0);
  });

  it("classifies and terminates no unrelated process after the root PID is reused", async () => {
    const seen = new Map();
    // 1. While the verified root is alive, its genuine child is observed.
    recordObservations({
      table: { rows: [row(100, 1, 1000, "root"), row(300, 100, 2000, "genuine-child")] },
      mode: "parent-tree",
      owned: [verifiedRoot],
      baselineKeys: new Set(),
      seen,
    });
    expect([...seen.keys()]).toEqual([processKey(row(100, 1, 1000)), processKey(row(300, 100, 2000))]);

    // 2. The root dies; PID 100 is reused by an unrelated process that starts its own child. The
    //    gate has not yet seen the exit event, so the owned record still says running.
    const reusedTable = {
      available: true,
      rows: [row(100, 1, 9000, "unrelated-reuser"), row(301, 100, 9500, "unrelated-child"), row(300, 100, 2000, "genuine-child")],
    };
    recordObservations({ table: reusedTable, mode: "parent-tree", owned: [verifiedRoot], baselineKeys: new Set(), seen });
    expect(names([...seen.values()].map((entry) => entry.row))).toEqual(["root", "genuine-child"]);

    // 3. Only the genuine child survives; the reuser and its child are never survivors.
    const survivors = findSurvivors({ finalTable: reusedTable, mode: "parent-tree", baselineKeys: new Set(), seen });
    expect(survivors.map((item) => item.pid)).toEqual([300]);

    // 4. Revalidation: if PID 300 has also been reused by cleanup time, nothing is killed.
    const killed = [];
    const reusedAgain = async () => ({ available: true, mode: "parent-tree", rows: [row(300, 1, 9999, "another-reuser")] });
    const none = await terminateVerifiedSurvivors({ rows: survivors, processTable: reusedAgain, kill: (pid) => killed.push(pid) });
    expect(none.attempted).toEqual([]);
    expect(killed).toEqual([]);

    // 5. With an exact identity match, only the genuine child is terminated.
    const matching = async () => reusedTable;
    const done = await terminateVerifiedSurvivors({ rows: survivors, processTable: matching, kill: (pid) => killed.push(pid) });
    expect(done.attempted).toEqual(["genuine-child#300"]);
    expect(killed).toEqual([300]);
  });

  it("does not terminate anything when revalidation cannot enumerate processes", async () => {
    const killed = [];
    const unavailable = async () => ({ available: false, mode: "parent-tree", rows: [], error: "timed out" });
    const result = await terminateVerifiedSurvivors({ rows: [row(300, 100, 2000)], processTable: unavailable, kill: (pid) => killed.push(pid) });
    expect(killed).toEqual([]);
    expect(result.errors[0]).toMatch(/unavailable/);
  });
});

describe("bounded process enumeration", () => {
  const hungLister = { command: process.execPath, args: ["-e", "setInterval(() => {}, 1000)"], parser: parseUnixRows };

  it("times out a hung lister, stops only that lister and reports enumeration unavailable", async () => {
    const result = await listProcesses({ ...hungLister, mode: "parent-tree", timeoutMs: 500 });
    expect(result.available).toBe(false);
    expect(result.timedOut).toBe(true);
    expect(result.rows).toEqual([]);
    expect(result.error).toMatch(/timed out after 500ms/);
    expect(result.listerPid).toBeGreaterThan(0);
    expect(await waitUntilDead(result.listerPid)).toBe(true);
  });

  it("fails closed on a timed-out tree query instead of falling back to another mode", async () => {
    const calls = [];
    const table = createProcessTable({
      timeoutMs: 300,
      commands: { tree: hungLister, baseline: { command: process.execPath, args: ["-e", "console.log('[]')"], parser: () => [] } },
      list: async (spec) => {
        calls.push(spec.mode);
        return listProcesses(spec);
      },
    });
    const result = await table(null);
    expect(result.available).toBe(false);
    expect(calls).toEqual(["parent-tree"]);
  });

  it("reports an unusable lister as unavailable, never as an empty table", async () => {
    const result = await listProcesses({
      command: path.join(scratch, "missing-lister.exe"),
      args: [],
      parser: parseUnixRows,
      mode: "parent-tree",
      timeoutMs: 5000,
    });
    expect(result.available).toBe(false);
  });
});

describe("owned process spawn failure", () => {
  it("settles a nonexistent executable as a spawn failure that needs no stopping", async () => {
    const owned = startOwnedProcess({
      label: "missing",
      executable: path.join(scratch, "definitely-missing-executable.exe"),
      write: silent,
    });
    const outcome = await owned.exited;
    expect(owned.pid).toBeNull();
    expect(outcome.error).toMatch(/spawn failed: ENOENT/);
    const stopped = await stopOwnedProcess(owned, { timeoutMs: 1000, write: silent });
    expect(stopped).toEqual({ stopped: true, outcome });
  });
});

describe("owned process identity capture", () => {
  const ownedAt = (spawnedAt) => ({
    pid: 77,
    spawnedAt,
    running: true,
    identity: null,
    identityError: null,
  });

  it("uses millisecond precision for Windows-style process timestamps", async () => {
    const tooOld = ownedAt(5000);
    await captureIdentity({
      owned: tooOld,
      mode: "parent-tree",
      processTable: async () => ({
        available: true,
        rows: [row(77, 1, 4998, "stale")],
        creationResolutionMs: 1,
      }),
    });
    expect(tooOld.identity).toBeNull();
    expect(tooOld.identityError).toMatch(/creation time/);

    const current = ownedAt(5000);
    await captureIdentity({
      owned: current,
      mode: "parent-tree",
      processTable: async () => ({
        available: true,
        rows: [row(77, 1, 5001, "current")],
        creationResolutionMs: 1,
      }),
    });
    expect(current.identity?.name).toBe("current");
  });

  it("declares each process table's timestamp resolution", () => {
    // Windows CIM reports milliseconds. `ps lstart` is second-truncated and derived from a
    // second-resolution boot time, so a genuine child can appear up to two seconds early.
    expect(defaultProcessCommands("win32").tree.creationResolutionMs).toBe(1);
    expect(defaultProcessCommands("win32").baseline.creationResolutionMs).toBe(1);
    expect(defaultProcessCommands("linux").tree.creationResolutionMs).toBe(2000);
  });

  it("allows only one timestamp-resolution window for second-granularity ps output", async () => {
    const atBoundary = ownedAt(5000);
    await captureIdentity({
      owned: atBoundary,
      mode: "parent-tree",
      processTable: async () => ({
        available: true,
        rows: [row(77, 1, 4000, "rounded-to-second")],
        creationResolutionMs: 1000,
      }),
    });
    expect(atBoundary.identity?.name).toBe("rounded-to-second");

    const outsideBoundary = ownedAt(5000);
    await captureIdentity({
      owned: outsideBoundary,
      mode: "parent-tree",
      processTable: async () => ({
        available: true,
        rows: [row(77, 1, 3999, "too-old")],
        creationResolutionMs: 1000,
      }),
    });
    expect(outsideBoundary.identity).toBeNull();
    expect(outsideBoundary.identityError).toMatch(/creation time/);
  });
});

// ------------------------------------------------------------------------------ full gate runs

async function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const { port } = server.address();
      server.close(() => resolve(port));
    });
  });
}

const nodeScript = (label, code, env = {}) => ({
  label,
  executable: process.execPath,
  args: ["-e", code],
  options: { env: { ...process.env, ...env } },
});

const SERVER = "require('http').createServer((q, s) => s.end('ok')).listen(Number(process.env.PORT), '127.0.0.1');";
const PASSING_RUNNER = [
  "const fs = require('fs');",
  "fs.writeFileSync(process.env.REPORT, JSON.stringify({ stats: { expected: 1, unexpected: 0, skipped: 0, flaky: 0 }, suites: [] }));",
  "console.log('  1 passed (0.1s)');",
].join(" ");
// Starts a stand-in "browser" that outlives the runner, then hangs while producing output. It is
// detached because libuv otherwise places Windows children in a kill-on-close job, and the point
// is a real process that survives its parent being stopped.
const HANGING_RUNNER_WITH_BROWSER = [
  "const { spawn } = require('child_process'); const fs = require('fs');",
  "const browser = spawn(process.execPath, ['-e', 'setInterval(() => {}, 1000)'], { stdio: 'ignore', detached: true }); browser.unref();",
  "fs.writeFileSync(process.env.BROWSER_PID_FILE, String(browser.pid));",
  "setInterval(() => console.log('still running'), 500);",
].join(" ");

async function gateConfig({ runner = PASSING_RUNNER, web, bounds = {}, processTable } = {}) {
  const dir = mkdtempSync(path.join(scratch, "run-"));
  const [apiPort, webPort] = [await freePort(), await freePort()];
  const reportPath = path.join(dir, "results.json");
  const browserPidFile = path.join(dir, "browser.pid");
  return {
    browserPidFile,
    config: {
      ports: [apiPort, webPort],
      reportPath,
      noSkipsScript,
      bounds: {
        exitBoundSeconds: 10,
        inactivityTimeoutSeconds: 30,
        overallTimeoutSeconds: 60,
        serviceStopTimeoutMs: 3000,
        buildTimeoutSeconds: 30,
        processQueryTimeoutMs: 30_000,
        processSettleTimeoutMs: 3000,
        processSettlePollMs: 100,
        sampleIntervalMs: 500,
        ...bounds,
      },
      processTable: processTable ?? createProcessTable({ timeoutMs: 30_000, commands: defaultProcessCommands() }),
      readTreeState: () => ({ ok: true, lines: [], comparable: [], fingerprint: "unchanged" }),
      evidenceRefresh: false,
      write: silent,
      build: nodeScript("fake-build", "process.exit(0)"),
      backend: { ...nodeScript("fake-api", SERVER, { PORT: String(apiPort) }), readyUrl: `http://127.0.0.1:${apiPort}/`, readyTimeoutMs: 20_000 },
      web: web ?? { ...nodeScript("fake-web", SERVER, { PORT: String(webPort) }), readyUrl: `http://127.0.0.1:${webPort}/`, readyTimeoutMs: 20_000 },
      playwright: nodeScript("fake-playwright", runner, { REPORT: reportPath, BROWSER_PID_FILE: browserPidFile }),
    },
  };
}

describe("runGate with real child processes", () => {
  it("passes a clean run and verifies the identity of every owned process that was still running", async () => {
    const { config } = await gateConfig();
    const { summary, exitCode } = await runGate(config);
    expect(summary.failures, JSON.stringify(summary.process_survivor_details ?? [], null, 2)).toEqual([]);
    expect(exitCode).toBe(0);
    expect(summary.exited_by_itself).toBe(true);
    expect(summary.seconds_from_summary_to_exit).not.toBeNull();
    for (const item of Object.values(summary.owned_processes)) expect(item.identity_error).toBeNull();
    if (summary.process_check_mode === "parent-tree") {
      // The long-running services are verified. The stand-in build and runner may exit before the
      // identity query returns; such a process is never trusted as a root.
      expect(summary.owned_processes.backend.identity_verified).toBe(true);
      expect(summary.owned_processes.web.identity_verified).toBe(true);
    }
  }, 180_000);

  it("turns a missing executable into an ordinary failure with bounded cleanup and a summary", async () => {
    const base = await gateConfig();
    const web = {
      label: "missing-web",
      executable: path.join(scratch, "definitely-missing-web.exe"),
      args: [],
      options: {},
      readyUrl: `http://127.0.0.1:${base.config.ports[1]}/`,
      readyTimeoutMs: 20_000,
    };
    const { config } = { config: { ...base.config, web } };
    const { summary, exitCode } = await runGate(config);
    expect(exitCode).toBe(1);
    expect(summary.result).toBe("failed");
    expect(summary.failures.join("\n")).toMatch(/missing-web could not be started \(spawn failed: ENOENT/);
    expect(summary.owned_processes.web.outcome.error).toMatch(/ENOENT/);
    expect(summary.owned_processes.playwright).toBeUndefined();
    expect(summary.owned_backend_stopped).toBe(true);
    expect(summary[`port_${config.ports[0]}_free`]).toBe(true);
    expect(summary.processes_still_alive).toEqual([]);
  }, 180_000);

  it("stops a hung runner at the overall timeout and terminates its verified surviving browser", async () => {
    const { config, browserPidFile } = await gateConfig({
      runner: HANGING_RUNNER_WITH_BROWSER,
      bounds: { overallTimeoutSeconds: 8 },
    });
    let browserPid = null;
    try {
      const { summary, exitCode } = await runGate(config);
      browserPid = existsSync(browserPidFile) ? Number(readFileSync(browserPidFile, "utf8")) : null;
      expect(exitCode).toBe(1);
      expect(browserPid).toBeGreaterThan(0);
      expect(summary.failures).toContain("Playwright exceeded the overall timeout of 8s");
      expect(summary.owned_web_stopped).toBe(true);
      expect(summary.owned_backend_stopped).toBe(true);
      if (summary.process_check_mode === "parent-tree") {
        expect(summary.processes_still_alive.some((item) => item.endsWith(`#${browserPid}`))).toBe(true);
        expect(summary.survivors_terminated_by_gate.some((item) => item.endsWith(`#${browserPid}`))).toBe(true);
        expect(summary.survivors_remaining_after_cleanup).toEqual([]);
        expect(await waitUntilDead(browserPid)).toBe(true);
      }
    } finally {
      if (browserPid) strayPids.add(browserPid);
    }
  }, 240_000);

  it("fails closed with a summary when process enumeration hangs, leaving no lister running", async () => {
    const listerPids = [];
    const processTable = createProcessTable({
      timeoutMs: 700,
      commands: { tree: { command: process.execPath, args: ["-e", "setInterval(() => {}, 1000)"], parser: parseUnixRows }, baseline: null },
      list: async (spec) => {
        const result = await listProcesses(spec);
        listerPids.push(result.listerPid);
        return result;
      },
    });
    const { config } = await gateConfig({ processTable });
    let prepareCalls = 0;
    let spawnCalls = 0;
    config.prepareBuild = () => {
      prepareCalls += 1;
      return { status: 0 };
    };
    const forbidSpawn = () => {
      spawnCalls += 1;
      throw new Error("execution must not start without a baseline");
    };
    for (const key of ["build", "backend", "web", "playwright"]) config[key].spawnImpl = forbidSpawn;
    const { summary, exitCode } = await runGate(config);
    expect(exitCode).toBe(1);
    expect(summary.execution_started).toBe(false);
    expect(summary.owned_processes).toEqual({});
    expect(summary.report_check).toMatch(/execution was prevented/);
    expect(summary.failures.join("\n")).not.toMatch(/Playwright JSON report/);
    expect(prepareCalls).toBe(0);
    expect(spawnCalls).toBe(0);
    expect(summary.process_check_mode).toBe("unavailable");
    expect(summary.process_enumeration_available).toBe(false);
    expect(summary.failures.join("\n")).toMatch(/process enumeration was unavailable before the run: process enumeration timed out after 700ms/);
    expect(listerPids.length).toBeGreaterThan(0);
    for (const pid of listerPids) expect(await waitUntilDead(pid)).toBe(true);
  }, 180_000);

  it("settles an in-flight hung sample before producing the summary", async () => {
    let calls = 0;
    let inFlight = 0;
    const hung = createProcessTable({
      timeoutMs: 1500,
      commands: { tree: { command: process.execPath, args: ["-e", "setInterval(() => {}, 1000)"], parser: parseUnixRows }, baseline: null },
    });
    const processTable = async (mode) => {
      calls += 1;
      if (calls === 1) return { available: true, mode: "parent-tree", rows: [], error: null };
      inFlight += 1;
      try {
        return await hung(mode);
      } finally {
        inFlight -= 1;
      }
    };
    const { config } = await gateConfig({ processTable, bounds: { sampleIntervalMs: 100 } });
    const { summary, exitCode } = await runGate(config);
    expect(inFlight).toBe(0);
    expect(exitCode).toBe(1);
    expect(summary.failures.join("\n")).toMatch(/timed out after 1500ms/);
    expect(summary.process_enumeration_available).toBe(false);
  }, 180_000);
});

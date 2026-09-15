#!/usr/bin/env node
/**
 * No-hang acceptance gate for the Playwright suite.
 *
 * Runs Playwright once and fails (non-zero) unless:
 *   - every test passed and nothing was skipped (JSON report);
 *   - Playwright exited with code 0, by itself, within EXIT_BOUND_SECONDS of printing its summary;
 *   - ports 3000 and 8010 no longer accept connections;
 *   - no process that was a descendant of this Playwright run is still alive;
 *   - `git status --short` is empty afterwards (ordinary runs must not rewrite tracked files).
 *
 * If Playwright hangs, the gate prints the surviving descendants of its own run, terminates only
 * that known process tree, and fails. It never enumerates or kills unrelated Chrome, Node or Python
 * processes.
 */
import { spawn, spawnSync } from "node:child_process";
import { existsSync, readFileSync, statSync } from "node:fs";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repo = path.resolve(root, "..");
const cli = path.join(root, "node_modules", "@playwright", "test", "cli.js");
const report = path.join(root, "playwright-report", "results.json");
const EXIT_BOUND_SECONDS = Number(process.env.E2E_EXIT_BOUND_SECONDS ?? 60);
const OVERALL_TIMEOUT_SECONDS = Number(process.env.E2E_OVERALL_TIMEOUT_SECONDS ?? 1800);
const isWindows = process.platform === "win32";

const WINDOWS_QUERY =
  "Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,Name,CreationDate | ConvertTo-Json -Compress";

function parseTable(stdout) {
  if (isWindows) {
    const rows = JSON.parse(stdout || "[]");
    return (Array.isArray(rows) ? rows : [rows]).map((row) => ({
      pid: row.ProcessId,
      ppid: row.ParentProcessId,
      name: row.Name,
      created: String(row.CreationDate),
    }));
  }
  return stdout
    .split("\n")
    .filter(Boolean)
    .map((line) => {
      const parts = line.trim().split(/\s+/);
      return { pid: Number(parts[0]), ppid: Number(parts[1]), created: parts.slice(2, 7).join(" "), name: parts.slice(7).join(" ") };
    });
}

/**
 * Asynchronous process listing. A synchronous listing would block this process's event loop, stop it
 * draining Playwright's output pipe, and so stall Playwright itself.
 */
function processTable() {
  return new Promise((resolve) => {
    const command = isWindows ? "powershell.exe" : "ps";
    const args = isWindows ? ["-NoProfile", "-NonInteractive", "-Command", WINDOWS_QUERY] : ["-eo", "pid=,ppid=,lstart=,comm="];
    const lister = spawn(command, args, { windowsHide: true, stdio: ["ignore", "pipe", "ignore"] });
    let stdout = "";
    lister.stdout.on("data", (chunk) => {
      stdout += chunk;
    });
    lister.once("error", () => resolve([]));
    lister.once("close", () => {
      try {
        resolve(parseTable(stdout));
      } catch {
        resolve([]);
      }
    });
  });
}

function descendants(table, rootPid) {
  const byParent = new Map();
  for (const row of table) {
    if (!byParent.has(row.ppid)) byParent.set(row.ppid, []);
    byParent.get(row.ppid).push(row);
  }
  const found = [];
  const queue = [rootPid];
  while (queue.length) {
    const pid = queue.shift();
    for (const child of byParent.get(pid) ?? []) {
      if (child.pid !== pid) {
        found.push(child);
        queue.push(child.pid);
      }
    }
  }
  return found;
}

function portOpen(port) {
  return new Promise((resolve) => {
    const socket = net.connect({ port, host: "127.0.0.1" });
    socket.setTimeout(1500);
    socket.once("connect", () => {
      socket.destroy();
      resolve(true);
    });
    socket.once("timeout", () => {
      socket.destroy();
      resolve(false);
    });
    socket.once("error", () => resolve(false));
  });
}

function killKnownTree(pid) {
  if (isWindows) {
    spawnSync("taskkill", ["/PID", String(pid), "/T", "/F"], { windowsHide: true });
  } else {
    try {
      process.kill(pid, "SIGKILL");
    } catch {
      // already gone
    }
  }
}

const summary = { exit_bound_seconds: EXIT_BOUND_SECONDS };
const failures = [];
const seen = new Map();
const reportMtimeBefore = existsSync(report) ? statSync(report).mtimeMs : 0;
const started = Date.now();

const child = spawn(process.execPath, [cli, "test", ...process.argv.slice(2)], {
  cwd: root,
  env: process.env,
  stdio: ["ignore", "pipe", "pipe"],
  windowsHide: true,
});
let summaryAt = null;
const onOutput = (stream) => (chunk) => {
  stream.write(chunk);
  if (summaryAt === null && /^\s+\d+ (passed|failed|flaky)/m.test(chunk.toString())) {
    summaryAt = Date.now();
  }
};
child.stdout.on("data", onOutput(process.stdout));
child.stderr.on("data", onOutput(process.stderr));

const exited = new Promise((resolve) => child.once("exit", (code, signal) => resolve({ code, signal })));
let snapshotting = false;
const snapshot = setInterval(async () => {
  if (snapshotting) return;
  snapshotting = true;
  try {
    for (const row of descendants(await processTable(), child.pid)) {
      seen.set(row.pid, row);
    }
  } finally {
    snapshotting = false;
  }
}, 8000);

let outcome = null;
let hung = false;
while (outcome === null) {
  outcome = await Promise.race([exited, new Promise((resolve) => setTimeout(() => resolve(null), 1000))]);
  const now = Date.now();
  let reason = null;
  if (outcome === null && summaryAt !== null && now - summaryAt > EXIT_BOUND_SECONDS * 1000) {
    reason = `Playwright did not exit within ${EXIT_BOUND_SECONDS}s of its summary`;
  } else if (outcome === null && now - started > OVERALL_TIMEOUT_SECONDS * 1000) {
    reason = `Playwright exceeded the overall timeout of ${OVERALL_TIMEOUT_SECONDS}s`;
  }
  if (reason !== null) {
    hung = true;
    const survivors = descendants(await processTable(), child.pid);
    summary.hang_survivors = survivors.map((row) => `${row.name}#${row.pid}`);
    failures.push(reason);
    killKnownTree(child.pid);
    outcome = await exited;
  }
}
clearInterval(snapshot);
const finished = Date.now();
summary.playwright_exit_code = outcome.code;
summary.playwright_signal = outcome.signal;
summary.total_seconds = Math.round((finished - started) / 1000);
summary.seconds_from_summary_to_exit = summaryAt === null ? null : Math.round((finished - summaryAt) / 100) / 10;
summary.exited_by_itself = !hung;
if (outcome.code !== 0) failures.push(`Playwright exit code ${outcome.code}`);
if (summaryAt === null) failures.push("Playwright never printed a result summary");

// Known descendants of this run must be gone (matched by pid and creation time, so a reused pid is not confused).
await new Promise((resolve) => setTimeout(resolve, 1500));
const table = await processTable();
const alive = [...seen.values()].filter((row) => table.some((now) => now.pid === row.pid && now.created === row.created));
summary.descendants_observed = seen.size;
summary.descendants_still_alive = alive.map((row) => `${row.name}#${row.pid}`);
if (alive.length) failures.push(`${alive.length} process(es) started by this run are still alive`);

for (const port of [3000, 8010]) {
  const open = await portOpen(port);
  summary[`port_${port}_free`] = !open;
  if (open) failures.push(`port ${port} is still accepting connections`);
}

if (!existsSync(report) || statSync(report).mtimeMs <= reportMtimeBefore) {
  failures.push("Playwright JSON report was not written by this run");
} else {
  const data = JSON.parse(readFileSync(report, "utf8"));
  const stats = data.stats ?? {};
  summary.expected = stats.expected;
  summary.unexpected = stats.unexpected;
  summary.skipped = stats.skipped;
  summary.flaky = stats.flaky;
  if (stats.unexpected || stats.flaky) failures.push(`${stats.unexpected} unexpected, ${stats.flaky} flaky`);
  const noSkips = spawnSync(process.execPath, [path.join(root, "scripts", "assert-no-skips.mjs"), report], {
    encoding: "utf8",
  });
  summary.no_skip_gate = noSkips.status === 0 ? "passed" : "failed";
  if (noSkips.status !== 0) failures.push(noSkips.stderr.trim() || "skipped tests reported");
}

const status = spawnSync("git", ["status", "--short", "--untracked-files=all"], { cwd: repo, encoding: "utf8" });
if (status.status !== 0) failures.push("git status could not be read");
// Keep the leading status column: " M path" and "M  path" differ, and the path starts at column 3.
summary.git_status_short = status.stdout
  .split(/\r?\n/)
  .map((line) => line.trimEnd())
  .filter(Boolean);
// An explicit evidence refresh may change tracked screenshots and nothing else.
const evidenceRefresh = process.env.UPDATE_VISUAL_EVIDENCE === "1";
const unexpectedChanges = summary.git_status_short.filter(
  (line) => !(evidenceRefresh && line.slice(3).startsWith("docs/evidence/screenshots/")),
);
summary.evidence_refresh = evidenceRefresh;
if (unexpectedChanges.length) failures.push("the working tree changed during the test run");

summary.result = failures.length ? "failed" : "passed";
summary.failures = failures;
console.log(`\n[e2e-gate] ${JSON.stringify(summary, null, 2)}`);
process.exit(failures.length ? 1 : 0);

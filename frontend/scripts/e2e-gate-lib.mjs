/**
 * Lifecycle and process-verification logic for the bounded Playwright acceptance gate.
 *
 * `scripts/e2e-gate.mjs` supplies the real commands; tests supply synthetic commands, process
 * tables and bounds. Nothing here enumerates or terminates a process that the gate cannot prove it
 * started: owned processes are identified by PID plus creation time, descendants are attributed
 * only through a verified live root, and survivors are revalidated immediately before termination.
 */
import { spawn, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, readFileSync, statSync } from "node:fs";
import net from "node:net";
import path from "node:path";

export const delay = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

const message = (error) => (error instanceof Error ? error.message : String(error));

export function positiveNumber(value, label) {
  if (!Number.isFinite(value) || value <= 0) {
    throw new Error(`${label} must be a positive number.`);
  }
  return value;
}

export function boundsFromEnv(env) {
  return {
    exitBoundSeconds: positiveNumber(Number(env.E2E_EXIT_BOUND_SECONDS ?? 60), "E2E_EXIT_BOUND_SECONDS"),
    inactivityTimeoutSeconds: positiveNumber(
      Number(env.E2E_INACTIVITY_TIMEOUT_SECONDS ?? 90),
      "E2E_INACTIVITY_TIMEOUT_SECONDS",
    ),
    overallTimeoutSeconds: positiveNumber(Number(env.E2E_OVERALL_TIMEOUT_SECONDS ?? 600), "E2E_OVERALL_TIMEOUT_SECONDS"),
    serviceStopTimeoutMs: positiveNumber(Number(env.E2E_SERVICE_STOP_TIMEOUT_MS ?? 10_000), "E2E_SERVICE_STOP_TIMEOUT_MS"),
    buildTimeoutSeconds: positiveNumber(Number(env.E2E_BUILD_TIMEOUT_SECONDS ?? 900), "E2E_BUILD_TIMEOUT_SECONDS"),
    processQueryTimeoutMs: positiveNumber(
      Number(env.E2E_PROCESS_QUERY_TIMEOUT_MS ?? 20_000),
      "E2E_PROCESS_QUERY_TIMEOUT_MS",
    ),
    sampleIntervalMs: 3000,
    settleDelayMs: 1500,
  };
}

// ------------------------------------------------------------------------------------ tables

export const WINDOWS_TREE_QUERY =
  "$ErrorActionPreference = 'Stop'; Get-CimInstance Win32_Process -ErrorAction Stop | " +
  "Select-Object ProcessId,ParentProcessId,Name,CreationDate | ConvertTo-Json -Compress";
export const WINDOWS_BASELINE_QUERY = [
  "$items = @(Get-Process -Name node,python,python3,chrome,chrome-headless-shell,headless_shell,msedge,firefox -ErrorAction SilentlyContinue)",
  "$rows = @($items | ForEach-Object { try { [PSCustomObject]@{ ProcessId=$_.Id; ParentProcessId=$null; Name=$_.ProcessName; CreationDate=$_.StartTime.ToUniversalTime().ToString('o') } } catch {} })",
  "$rows | ConvertTo-Json -Compress",
].join("; ");

export function parseWindowsRows(stdout) {
  const raw = stdout.trim();
  if (!raw) return [];
  const rows = JSON.parse(raw);
  return (Array.isArray(rows) ? rows : [rows]).map((row) => ({
    pid: Number(row.ProcessId),
    ppid: row.ParentProcessId === null || row.ParentProcessId === undefined ? null : Number(row.ParentProcessId),
    name: String(row.Name),
    created: String(row.CreationDate),
  }));
}

export function parseUnixRows(stdout) {
  return stdout
    .split("\n")
    .filter((line) => line.trim())
    .map((line) => {
      const parts = line.trim().split(/\s+/);
      return {
        pid: Number(parts[0]),
        ppid: Number(parts[1]),
        created: parts.slice(2, 7).join(" "),
        name: parts.slice(7).join(" "),
      };
    });
}

export function defaultProcessCommands(platform = process.platform) {
  if (platform !== "win32") {
    return {
      tree: { command: "ps", args: ["-eo", "pid=,ppid=,lstart=,comm="], parser: parseUnixRows },
      baseline: null,
    };
  }
  const powershell = (query) => ["-NoProfile", "-NonInteractive", "-Command", query];
  return {
    tree: { command: "powershell.exe", args: powershell(WINDOWS_TREE_QUERY), parser: parseWindowsRows },
    baseline: { command: "powershell.exe", args: powershell(WINDOWS_BASELINE_QUERY), parser: parseWindowsRows },
  };
}

/**
 * Runs one process-listing command with a hard bound. On timeout only this call's lister child is
 * terminated, and the result is reported as unavailable (never as an empty successful table).
 */
export function listProcesses({ command, args, parser, mode, timeoutMs, spawnImpl = spawn }) {
  return new Promise((resolve) => {
    let child = null;
    let settled = false;
    let timer = null;
    const finish = (result) => {
      if (settled) return;
      settled = true;
      if (timer !== null) clearTimeout(timer);
      resolve({ mode, rows: [], error: null, timedOut: false, listerPid: child?.pid ?? null, ...result });
    };
    try {
      child = spawnImpl(command, args, { windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
    } catch (error) {
      finish({ available: false, error: `process lister could not start: ${message(error)}` });
      return;
    }
    let stdout = "";
    let stderr = "";
    child.stdout?.on("data", (chunk) => {
      stdout += chunk;
    });
    child.stderr?.on("data", (chunk) => {
      stderr += chunk;
    });
    child.once("error", (error) => finish({ available: false, error: `process lister failed: ${message(error)}` }));
    child.once("close", (code) => {
      if (code !== 0) {
        finish({ available: false, error: stderr.trim() || `process lister exited ${code}` });
        return;
      }
      try {
        finish({ available: true, rows: parser(stdout) });
      } catch (error) {
        finish({ available: false, error: `process list parse failed: ${message(error)}` });
      }
    });
    timer = setTimeout(() => {
      try {
        child.kill("SIGKILL");
      } catch {
        // The lister is already gone.
      }
      child.stdout?.destroy();
      child.stderr?.destroy();
      finish({ available: false, timedOut: true, error: `process enumeration timed out after ${timeoutMs}ms` });
    }, timeoutMs);
  });
}

/**
 * Parent-tree enumeration is preferred. The baseline-delta inventory is used only when the tree
 * query fails outright; a timed-out tree query fails closed instead of silently changing mode.
 */
export function createProcessTable({ timeoutMs, commands = defaultProcessCommands(), list = listProcesses }) {
  return async function processTable(requiredMode = null) {
    if (requiredMode !== "baseline-delta" || !commands.baseline) {
      const tree = await list({ ...commands.tree, mode: "parent-tree", timeoutMs });
      if (tree.available || tree.timedOut || requiredMode === "parent-tree" || !commands.baseline) return tree;
    }
    return list({ ...commands.baseline, mode: "baseline-delta", timeoutMs });
  };
}

// ---------------------------------------------------------------------------------- identity

export function processKey(row) {
  return `${row.pid}:${row.created}`;
}

/** Milliseconds since the epoch from CIM (`/Date(ms)/`), ISO or `ps lstart` text; NaN if unknown. */
export function createdMs(row) {
  const cim = /Date\((\d+)/.exec(String(row.created));
  return cim ? Number(cim[1]) : Date.parse(row.created);
}

export function identityOf(row) {
  return { pid: row.pid, created: row.created, name: row.name };
}

/** Same process only when both the PID and the creation time match. */
export function sameProcess(row, identity) {
  if (!row || !identity || row.pid !== identity.pid) return false;
  if (row.created === identity.created) return true;
  const a = createdMs(row);
  const b = createdMs(identity);
  return Number.isFinite(a) && Number.isFinite(b) && Math.abs(a - b) <= 1;
}

/**
 * Descendants of a root identified by PID plus creation time. If the table's row for that PID has
 * a different creation time, the PID was reused and nothing is attributed. Each PID is visited once
 * (the Windows parent graph can contain cycles), and a row created before its supposed parent - or
 * with an unknown creation time - is not a child: its real creator died and the PID was reused.
 */
export function descendantsOf(rows, rootIdentity) {
  const root = rows.find((row) => sameProcess(row, rootIdentity));
  if (!root) return { rootVerified: false, root: null, rows: [] };
  const byParent = new Map();
  for (const row of rows) {
    if (row.ppid === null || row.ppid === undefined) continue;
    if (!byParent.has(row.ppid)) byParent.set(row.ppid, []);
    byParent.get(row.ppid).push(row);
  }
  const found = [];
  const visited = new Set([root.pid]);
  const queue = [root];
  while (queue.length) {
    const parent = queue.shift();
    const parentCreated = createdMs(parent);
    for (const child of byParent.get(parent.pid) ?? []) {
      if (visited.has(child.pid)) continue;
      const childCreated = createdMs(child);
      if (!Number.isFinite(parentCreated) || !Number.isFinite(childCreated) || childCreated < parentCreated) continue;
      visited.add(child.pid);
      found.push(child);
      queue.push(child);
    }
  }
  return { rootVerified: true, root, rows: found };
}

/**
 * Records processes observed in one table. In parent-tree mode only live owned roots whose verified
 * identity is present contribute, so an exited or reused root PID never attributes new processes.
 */
export function recordObservations({ table, mode, owned, baselineKeys, seen }) {
  if (mode === "baseline-delta") {
    for (const row of table.rows) {
      if (!baselineKeys.has(processKey(row))) seen.set(processKey(row), { row, via: "baseline-delta" });
    }
    return;
  }
  for (const item of owned) {
    if (!item || !item.running || !item.identity) continue;
    const result = descendantsOf(table.rows, item.identity);
    if (!result.rootVerified) continue;
    seen.set(processKey(result.root), { row: result.root, via: item.label });
    for (const row of result.rows) seen.set(processKey(row), { row, via: item.label });
  }
}

export function findSurvivors({ finalTable, mode, baselineKeys, seen }) {
  if (mode === "baseline-delta") {
    return finalTable.rows.filter((row) => !baselineKeys.has(processKey(row)));
  }
  return [...seen.values()]
    .map((entry) => entry.row)
    .filter((row) => finalTable.rows.some((current) => sameProcess(current, row)));
}

/**
 * Terminates only survivors that were attributed through a verified live root, after matching each
 * one again by PID and creation time in a fresh, bounded table query.
 */
export async function terminateVerifiedSurvivors({
  rows,
  processTable,
  kill = (pid) => process.kill(pid, "SIGKILL"),
  selfPid = process.pid,
}) {
  let table;
  try {
    table = await processTable("parent-tree");
  } catch (error) {
    return { attempted: [], errors: [`process enumeration failed before cleanup: ${message(error)}`] };
  }
  if (!table.available) {
    return { attempted: [], errors: [`process enumeration unavailable before cleanup: ${table.error}`] };
  }
  const attempted = [];
  const errors = [];
  for (const row of rows) {
    if (row.pid === selfPid) continue;
    if (!table.rows.some((current) => sameProcess(current, row))) continue;
    attempted.push(`${row.name}#${row.pid}`);
    try {
      kill(row.pid);
    } catch (error) {
      if (error?.code !== "ESRCH") errors.push(`${row.name}#${row.pid}: ${error?.code ?? message(error)}`);
    }
  }
  return { attempted, errors };
}

// ------------------------------------------------------------------------- owned processes

const defaultWrite = {
  stdout: (text) => process.stdout.write(text),
  stderr: (text) => process.stderr.write(text),
};

/**
 * Spawns an owned child with the error handler attached before any event can fire. A spawn failure
 * (missing executable, access denied, invalid options) settles the outcome with `error` set.
 */
export function startOwnedProcess({
  label,
  executable,
  args = [],
  options = {},
  write = defaultWrite,
  onOutput = null,
  spawnImpl = spawn,
}) {
  const owned = {
    label,
    child: null,
    pid: null,
    spawnedAt: Date.now(),
    running: false,
    settled: false,
    outcome: null,
    exitInfo: null,
    identity: null,
    identityError: null,
    errors: [],
  };
  let resolveExited;
  owned.exited = new Promise((resolve) => {
    resolveExited = resolve;
  });
  const settle = (outcome) => {
    if (owned.settled) return;
    owned.settled = true;
    owned.running = false;
    owned.outcome = outcome;
    resolveExited(outcome);
  };
  try {
    owned.child = spawnImpl(executable, args, { ...options, windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
  } catch (error) {
    settle({ code: null, signal: null, error: `spawn failed: ${message(error)}` });
    return owned;
  }
  const child = owned.child;
  owned.pid = typeof child.pid === "number" ? child.pid : null;
  owned.running = owned.pid !== null;
  child.on("error", (error) => {
    const detail = error?.code ? `${error.code}: ${message(error)}` : message(error);
    if (owned.pid === null) {
      settle({ code: null, signal: null, error: `spawn failed: ${detail}` });
    } else {
      owned.errors.push(detail);
    }
  });
  if (owned.pid === null) {
    // Node reports spawn failures through the error event; this only guarantees the outcome settles.
    setTimeout(() => settle({ code: null, signal: null, error: "spawn failed: no process was created" }), 5000).unref();
  }
  child.once("exit", (code, signal) => {
    owned.running = false;
    owned.exitInfo = { code, signal };
  });
  child.once("close", (code, signal) => settle({ code, signal, error: null }));
  // Output listeners are attached at spawn so nothing printed before identity capture is missed.
  child.stdout?.on("data", (chunk) => {
    write.stdout(`[${label}] ${chunk}`);
    onOutput?.(chunk);
  });
  child.stderr?.on("data", (chunk) => {
    write.stderr(`[${label}] ${chunk}`);
    onOutput?.(chunk);
  });
  return owned;
}

/**
 * Verifies an owned child's identity immediately after spawning: the table row for its PID must
 * have been created no earlier than the spawn (allowing for `ps lstart` second granularity) and the
 * child must still be running after the query, so the PID cannot have been reused in between.
 */
export async function captureIdentity({ owned, processTable, mode }) {
  if (!owned || owned.pid === null) return;
  let table;
  try {
    table = await processTable(mode);
  } catch (error) {
    owned.identityError = `process enumeration failed: ${message(error)}`;
    return;
  }
  if (!table.available) {
    owned.identityError = `process enumeration unavailable: ${table.error}`;
    return;
  }
  if (!owned.running) return;
  const row = table.rows.find((candidate) => candidate.pid === owned.pid);
  if (!row) {
    owned.identityError = "not present in the process table while running";
    return;
  }
  const created = createdMs(row);
  if (!Number.isFinite(created) || created < owned.spawnedAt - 2000) {
    owned.identityError = "process-table creation time does not match the spawn";
    return;
  }
  owned.identity = identityOf(row);
}

export async function stopOwnedProcess(owned, { timeoutMs, write = defaultWrite }) {
  if (!owned) return { stopped: true, outcome: null };
  if (owned.settled) return { stopped: true, outcome: owned.outcome };
  const waitFor = async (milliseconds) => {
    const deadline = Date.now() + milliseconds;
    while (Date.now() < deadline) {
      const outcome = await Promise.race([owned.exited, delay(100).then(() => null)]);
      if (outcome !== null) return outcome;
      // Exited, but a grandchild still holds the output pipes: the owned process itself has stopped.
      if (!owned.running && owned.exitInfo) return { ...owned.exitInfo, error: null, streams_open: true };
    }
    return null;
  };
  if (owned.running) {
    try {
      owned.child.kill("SIGTERM");
    } catch (error) {
      owned.errors.push(message(error));
    }
  }
  let outcome = await waitFor(timeoutMs);
  if (outcome === null) {
    write.stderr(`[e2e-gate] ${owned.label} did not stop after SIGTERM; sending SIGKILL.\n`);
    try {
      owned.child.kill("SIGKILL");
    } catch (error) {
      owned.errors.push(message(error));
    }
    outcome = await waitFor(5000);
  }
  if (outcome === null) {
    owned.child.stdout?.destroy();
    owned.child.stderr?.destroy();
    owned.child.unref();
    return { stopped: false, outcome: null };
  }
  return { stopped: true, outcome };
}

function describeOutcome(outcome) {
  if (!outcome) return "without an outcome";
  if (outcome.error) return `(${outcome.error})`;
  return outcome.signal ? `with signal ${outcome.signal}` : `with code ${outcome.code}`;
}

export function portOpen(port) {
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

async function waitForUrl(url, owned, timeoutMs) {
  const started = Date.now();
  while (Date.now() - started <= timeoutMs) {
    if (owned.pid === null || !owned.running) {
      const outcome = owned.settled ? owned.outcome : await Promise.race([owned.exited, delay(5000).then(() => null)]);
      if (outcome?.error) throw new Error(`${owned.label} could not be started ${describeOutcome(outcome)}`);
      throw new Error(`${owned.label} exited before becoming ready ${describeOutcome(outcome ?? owned.exitInfo)}`);
    }
    try {
      const response = await fetch(url, { redirect: "manual", signal: AbortSignal.timeout(2000) });
      if (response.status >= 200 && response.status < 500) return;
    } catch {
      // Not ready yet.
    }
    await delay(250);
  }
  throw new Error(`${owned.label} did not become ready within ${Math.round(timeoutMs / 1000)} seconds.`);
}

// ------------------------------------------------------------------------------ working tree

export const EVIDENCE_DIR = "docs/evidence/screenshots/";

/**
 * Status lines plus a SHA-256 fingerprint of the binary diff against HEAD and every untracked
 * file's bytes. A dirty tree is permitted before the run; the gate requires both to be identical
 * afterwards. Only an explicit evidence refresh excludes the screenshot directory.
 */
export function createTreeStateReader({ repo, evidenceRefresh }) {
  const isEvidencePath = (file) => file.replaceAll("\\", "/").startsWith(EVIDENCE_DIR);
  return function readTreeState() {
    const status = spawnSync("git", ["status", "--short", "--untracked-files=all"], { cwd: repo, encoding: "utf8" });
    const lines = (status.stdout ?? "")
      .split(/\r?\n/)
      .map((line) => line.trimEnd())
      .filter(Boolean);
    const pathspec = evidenceRefresh ? [".", `:(exclude)${EVIDENCE_DIR}`] : ["."];
    const diff = spawnSync("git", ["diff", "HEAD", "--binary", "--no-ext-diff", "--no-color", "--", ...pathspec], {
      cwd: repo,
      maxBuffer: 512 * 1024 * 1024,
    });
    const hash = createHash("sha256");
    let ok = status.status === 0 && diff.status === 0;
    if (diff.stdout) hash.update(diff.stdout);
    for (const line of lines) {
      if (!line.startsWith("?? ")) continue;
      const file = line.slice(3).replace(/^"|"$/g, "");
      if (evidenceRefresh && isEvidencePath(file)) continue;
      hash.update(`\0untracked\0${file}\0`);
      try {
        hash.update(readFileSync(path.join(repo, file)));
      } catch {
        ok = false;
      }
    }
    const comparable = lines.filter((line) => !(evidenceRefresh && isEvidencePath(line.slice(3))));
    return { ok, lines, comparable, fingerprint: hash.digest("hex") };
  };
}

// ------------------------------------------------------------------------------------- gate

/**
 * Runs the whole gate and always returns a summary; it never throws for an ordinary failure.
 *
 * config: { ports, reportPath, noSkipsScript, bounds, processTable, readTreeState, evidenceRefresh,
 *           prepareBuild?, build, backend, web, playwright, write?, kill? }
 * Each process spec: { label, executable, args, options, readyUrl?, readyTimeoutMs? }.
 */
export async function runGate(config) {
  const { bounds, processTable } = config;
  const write = config.write ?? defaultWrite;
  const failures = [];
  const fail = (text) => failures.push(text);
  const summary = {
    exit_bound_seconds: bounds.exitBoundSeconds,
    inactivity_timeout_seconds: bounds.inactivityTimeoutSeconds,
    overall_timeout_seconds: bounds.overallTimeoutSeconds,
    build_timeout_seconds: bounds.buildTimeoutSeconds,
    process_query_timeout_ms: bounds.processQueryTimeoutMs,
  };
  const gateStarted = Date.now();
  const seen = new Map();
  const owned = { build: null, backend: null, web: null, playwright: null };
  let baseline = { available: false, mode: "unavailable", rows: [], error: "not queried" };
  let baselineKeys = new Set();
  let samplingPromise = null;
  let sampler = null;
  let playwrightOutcome = null;
  let playwrightStarted = null;
  let playwrightFinishedAt = null;
  let playwrightExitedNaturally = false;
  let summaryAt = null;
  let lastOutputAt = null;
  let hung = false;

  const safeTable = async (mode) => {
    try {
      return await processTable(mode);
    } catch (error) {
      return { available: false, mode: mode ?? "unavailable", rows: [], error: message(error) };
    }
  };

  const sampleProcesses = () => {
    if (!baseline.available) return Promise.resolve();
    if (samplingPromise) return samplingPromise;
    samplingPromise = (async () => {
      try {
        const table = await safeTable(baseline.mode);
        if (!table.available) {
          fail(`process enumeration became unavailable during the run: ${table.error}`);
          return;
        }
        recordObservations({ table, mode: baseline.mode, owned: Object.values(owned), baselineKeys, seen });
      } catch (error) {
        fail(`process sampling failed: ${message(error)}`);
      }
    })().finally(() => {
      samplingPromise = null;
    });
    return samplingPromise;
  };

  const start = async (key, spec, onOutput = null) => {
    const item = startOwnedProcess({ ...spec, write, onOutput });
    owned[key] = item;
    if (item.pid !== null && baseline.available) {
      await captureIdentity({ owned: item, processTable: safeTable, mode: baseline.mode });
      if (baseline.mode === "parent-tree" && item.identityError) {
        fail(`identity of owned ${item.label} could not be verified: ${item.identityError}`);
      }
    }
    return item;
  };

  const reportPath = config.reportPath;
  const reportMtimeBefore = existsSync(reportPath) ? statSync(reportPath).mtimeMs : 0;
  let treeBefore = { ok: false, lines: [], comparable: [], fingerprint: "" };
  try {
    treeBefore = config.readTreeState();
  } catch (error) {
    fail(`the working tree could not be read before the run: ${message(error)}`);
  }
  if (!treeBefore.ok) fail("the working tree could not be read before the run");

  baseline = await safeTable(null);
  baselineKeys = new Set(baseline.rows.map(processKey));
  summary.process_check_mode = baseline.available ? baseline.mode : "unavailable";
  if (!baseline.available) fail(`process enumeration was unavailable before the run: ${baseline.error}`);

  try {
    for (const port of config.ports) {
      if (await portOpen(port)) throw new Error(`port ${port} is already accepting connections before the run`);
    }
    sampler = setInterval(() => void sampleProcesses(), bounds.sampleIntervalMs);

    if (config.prepareBuild) {
      const prepared = config.prepareBuild();
      if (prepared.status !== 0) {
        throw new Error(`build-directory preparation exited ${prepared.status ?? "without a code"}`);
      }
    }
    const build = await start("build", config.build);
    await sampleProcesses();
    const buildOutcome = await Promise.race([build.exited, delay(bounds.buildTimeoutSeconds * 1000).then(() => null)]);
    if (buildOutcome === null) {
      await sampleProcesses();
      const stopped = await stopOwnedProcess(build, { timeoutMs: bounds.serviceStopTimeoutMs, write });
      if (!stopped.stopped) fail("the owned build process could not be stopped within the bound");
      throw new Error(`production build exceeded ${bounds.buildTimeoutSeconds}s`);
    }
    if (buildOutcome.error) throw new Error(`production build could not be started ${describeOutcome(buildOutcome)}`);
    if (buildOutcome.code !== 0) throw new Error(`production build exited ${describeOutcome(buildOutcome)}`);

    const backend = await start("backend", config.backend);
    await waitForUrl(config.backend.readyUrl, backend, config.backend.readyTimeoutMs ?? 120_000);
    const web = await start("web", config.web);
    await waitForUrl(config.web.readyUrl, web, config.web.readyTimeoutMs ?? 60_000);

    let recentOutput = "";
    lastOutputAt = Date.now();
    const noteOutput = (chunk) => {
      lastOutputAt = Date.now();
      recentOutput = (recentOutput + chunk.toString()).slice(-16_000);
      if (summaryAt === null && /^\s+\d+ (passed|failed|flaky)/m.test(recentOutput)) summaryAt = Date.now();
    };
    const playwright = await start("playwright", config.playwright, noteOutput);
    playwrightStarted = playwright.spawnedAt;
    await sampleProcesses();

    while (playwrightOutcome === null) {
      const outcome = await Promise.race([playwright.exited, delay(500).then(() => null)]);
      if (outcome !== null) {
        playwrightOutcome = outcome;
        playwrightFinishedAt = Date.now();
        if (outcome.error) {
          fail(`Playwright could not be started ${describeOutcome(outcome)}`);
        } else {
          playwrightExitedNaturally = true;
        }
        break;
      }
      const now = Date.now();
      let reason = null;
      if (summaryAt !== null && now - summaryAt > bounds.exitBoundSeconds * 1000) {
        reason = `Playwright did not exit within ${bounds.exitBoundSeconds}s of its summary`;
      } else if (summaryAt === null && now - lastOutputAt > bounds.inactivityTimeoutSeconds * 1000) {
        reason = `Playwright produced no output for ${bounds.inactivityTimeoutSeconds}s before its summary`;
      } else if (now - playwrightStarted > bounds.overallTimeoutSeconds * 1000) {
        reason = `Playwright exceeded the overall timeout of ${bounds.overallTimeoutSeconds}s`;
      }
      if (reason !== null) {
        hung = true;
        fail(reason);
        await sampleProcesses();
        const stopped = await stopOwnedProcess(playwright, { timeoutMs: bounds.serviceStopTimeoutMs, write });
        playwrightOutcome = stopped.outcome ?? { code: null, signal: null, error: "not stopped" };
        playwrightFinishedAt = Date.now();
        if (!stopped.stopped) fail("the owned Playwright process could not be stopped within the bound");
      }
    }
  } catch (error) {
    fail(message(error));
  } finally {
    if (sampler !== null) clearInterval(sampler);
    // Settle an in-flight sample (itself bounded by the query timeout) before stopping anything.
    if (samplingPromise) await samplingPromise;
    const stopTimeout = { timeoutMs: bounds.serviceStopTimeoutMs, write };
    const buildStop = await stopOwnedProcess(owned.build, stopTimeout);
    if (!buildStop.stopped) fail("the owned build process could not be stopped during cleanup");
    if (owned.playwright && playwrightOutcome === null) {
      const stopped = await stopOwnedProcess(owned.playwright, stopTimeout);
      playwrightOutcome = stopped.outcome;
      playwrightFinishedAt = Date.now();
      if (!stopped.stopped) fail("the owned Playwright process could not be stopped during cleanup");
    }
    const webStop = await stopOwnedProcess(owned.web, stopTimeout);
    const backendStop = await stopOwnedProcess(owned.backend, stopTimeout);
    summary.owned_web_stopped = webStop.stopped;
    summary.owned_backend_stopped = backendStop.stopped;
    if (!webStop.stopped) fail("the owned Next server did not stop within the bound");
    if (!backendStop.stopped) fail("the owned API server did not stop within the bound");
  }

  summary.owned_processes = Object.fromEntries(
    Object.entries(owned)
      .filter(([, item]) => item)
      .map(([key, item]) => [
        key,
        {
          pid: item.pid,
          identity_verified: item.identity !== null,
          identity_error: item.identityError,
          outcome: item.outcome,
        },
      ]),
  );
  const playwright = owned.playwright;
  summary.playwright_exit_code = playwrightOutcome?.code ?? null;
  summary.playwright_signal = playwrightOutcome?.signal ?? null;
  summary.total_seconds = Math.round((Date.now() - gateStarted) / 1000);
  summary.playwright_seconds =
    playwrightStarted === null || playwrightFinishedAt === null
      ? null
      : Math.round((playwrightFinishedAt - playwrightStarted) / 1000);
  summary.seconds_from_summary_to_exit =
    summaryAt === null || playwrightFinishedAt === null ? null : Math.round((playwrightFinishedAt - summaryAt) / 100) / 10;
  summary.exited_by_itself = playwright !== null && !hung && playwrightExitedNaturally;
  if (playwrightOutcome && !playwrightOutcome.error && playwrightOutcome.code !== 0 && !hung) {
    fail(
      playwrightOutcome.signal
        ? `Playwright exited with signal ${playwrightOutcome.signal}`
        : `Playwright exit code ${playwrightOutcome.code}`,
    );
  }
  if (playwright !== null && summaryAt === null) fail("Playwright never printed a result summary");

  await delay(bounds.settleDelayMs);
  let alive = [];
  if (baseline.available) {
    const finalTable = await safeTable(baseline.mode);
    summary.process_enumeration_available = finalTable.available;
    if (!finalTable.available) {
      fail(`process enumeration was unavailable after the run: ${finalTable.error}`);
    } else {
      alive = findSurvivors({ finalTable, mode: baseline.mode, baselineKeys, seen });
      if (baseline.mode === "baseline-delta") {
        for (const row of alive) seen.set(processKey(row), { row, via: "baseline-delta" });
      }
    }
  } else {
    summary.process_enumeration_available = false;
  }
  summary.processes_observed = seen.size;
  summary.processes_still_alive = alive.map((row) => `${row.name}#${row.pid}`);
  if (alive.length) fail(`${alive.length} process(es) created by this run are still alive`);

  for (const port of config.ports) {
    const open = await portOpen(port);
    summary[`port_${port}_free`] = !open;
    if (open) fail(`port ${port} is still accepting connections`);
  }

  if (!existsSync(reportPath) || statSync(reportPath).mtimeMs <= reportMtimeBefore) {
    fail("Playwright JSON report was not written by this run");
  } else {
    try {
      const stats = JSON.parse(readFileSync(reportPath, "utf8")).stats ?? {};
      summary.expected = stats.expected;
      summary.unexpected = stats.unexpected;
      summary.skipped = stats.skipped;
      summary.flaky = stats.flaky;
      if (stats.unexpected || stats.flaky) fail(`${stats.unexpected} unexpected, ${stats.flaky} flaky`);
      const noSkips = spawnSync(process.execPath, [config.noSkipsScript, reportPath], { encoding: "utf8" });
      summary.no_skip_gate = noSkips.status === 0 ? "passed" : "failed";
      if (noSkips.status !== 0) fail(noSkips.stderr.trim() || "skipped tests reported");
    } catch (error) {
      fail(`Playwright JSON report could not be read: ${message(error)}`);
    }
  }

  let treeAfter = { ok: false, lines: [], comparable: [], fingerprint: "" };
  try {
    treeAfter = config.readTreeState();
  } catch (error) {
    fail(`the working tree could not be read after the run: ${message(error)}`);
  }
  if (!treeAfter.ok) fail("the working tree could not be read after the run");
  summary.working_tree_clean_before = treeBefore.lines.length === 0;
  summary.git_status_before = treeBefore.lines;
  summary.git_status_short = treeAfter.lines;
  summary.evidence_refresh = Boolean(config.evidenceRefresh);
  if (
    JSON.stringify(treeAfter.comparable) !== JSON.stringify(treeBefore.comparable) ||
    treeAfter.fingerprint !== treeBefore.fingerprint
  ) {
    fail("the test run changed the working tree");
  }

  // Survivors already fail the gate. In parent-tree mode they were attributed through a verified
  // live root, so remove them rather than strand them; baseline-delta cannot attribute processes
  // to this run and therefore never terminates anything.
  if (alive.length && baseline.mode === "parent-tree") {
    const cleanup = await terminateVerifiedSurvivors({ rows: alive, processTable: safeTable, kill: config.kill });
    summary.survivors_terminated_by_gate = cleanup.attempted;
    if (cleanup.errors.length) summary.survivor_cleanup_errors = cleanup.errors;
    await delay(500);
    const recheck = await safeTable("parent-tree");
    if (recheck.available) {
      const remaining = alive.filter((row) => recheck.rows.some((current) => sameProcess(current, row)));
      summary.survivors_remaining_after_cleanup = remaining.map((row) => `${row.name}#${row.pid}`);
      if (remaining.length) fail(`${remaining.length} surviving process(es) could not be terminated`);
    } else {
      fail(`process enumeration unavailable after survivor cleanup: ${recheck.error}`);
    }
  } else if (alive.length) {
    summary.survivor_cleanup = "not attempted: baseline-delta mode cannot attribute processes to this run";
  }

  summary.failures = [...new Set(failures)];
  summary.result = summary.failures.length ? "failed" : "passed";
  return { summary, exitCode: summary.failures.length ? 1 : 0 };
}

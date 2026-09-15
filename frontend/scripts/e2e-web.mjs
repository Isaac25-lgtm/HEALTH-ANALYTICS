#!/usr/bin/env node
/**
 * Playwright web server: build exactly as a release image does (no backend address available
 * at build time), then serve with the backend supplied only at runtime, in Render's bare
 * host:port form.
 *
 * Shutdown is explicit and bounded. The `next start` child never inherits this process's stdio,
 * so a surviving descendant cannot hold Playwright's pipes open. On a stop request the wrapper
 * signals only its own child, waits for it to exit, force-terminates only that child after a
 * timeout, and exits with an accurate code.
 */
import { spawn, spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const nextBin = path.join(root, "node_modules", "next", "dist", "bin", "next");
const backend = process.env.E2E_BACKEND_HOSTPORT;
const STOP_TIMEOUT_MS = 10_000;

if (!backend) {
  console.error("E2E_BACKEND_HOSTPORT is required.");
  process.exit(2);
}

const buildEnv = { ...process.env, NODE_ENV: "production" };
delete buildEnv.BACKEND_INTERNAL_URL;
delete buildEnv.NEXT_PUBLIC_API_BASE_URL;
const build = spawnSync(process.execPath, [nextBin, "build"], { cwd: root, env: buildEnv, stdio: "inherit" });
if (build.status !== 0) {
  process.exit(build.status ?? 1);
}

const server = spawn(process.execPath, [nextBin, "start", "--port", "3000"], {
  cwd: root,
  env: { ...process.env, NODE_ENV: "production", BACKEND_INTERNAL_URL: backend },
  stdio: ["ignore", "pipe", "pipe"],
  windowsHide: true,
});
server.stdout.pipe(process.stdout);
server.stderr.pipe(process.stderr);

let stopping = false;
const exited = new Promise((resolve) => {
  server.once("exit", (code, signal) => resolve({ code, signal }));
});

async function stop(reason) {
  if (stopping) {
    return;
  }
  stopping = true;
  if (server.exitCode === null && server.signalCode === null) {
    server.kill("SIGTERM");
    const outcome = await Promise.race([
      exited,
      new Promise((resolve) => setTimeout(() => resolve(null), STOP_TIMEOUT_MS)),
    ]);
    if (outcome === null) {
      console.error(`[e2e-web] next start did not stop within ${STOP_TIMEOUT_MS} ms after ${reason}; terminating it.`);
      server.kill("SIGKILL");
      await exited;
    }
  }
  process.exit(0);
}

for (const signal of ["SIGINT", "SIGTERM", "SIGBREAK", "SIGHUP"]) {
  process.on(signal, () => void stop(signal));
}

exited.then(({ code, signal }) => {
  if (stopping) {
    return;
  }
  console.error(`[e2e-web] next start exited unexpectedly (code ${code}, signal ${signal}).`);
  process.exit(code ?? 1);
});

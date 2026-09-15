#!/usr/bin/env node
/**
 * Playwright web server: build exactly as a release image does (no backend address available
 * at build time), then serve with the backend supplied only at runtime, in Render's bare
 * host:port form. Stops `next start` when Playwright stops this process.
 */
import { spawn, spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const nextBin = path.join(root, "node_modules", "next", "dist", "bin", "next");
const backend = process.env.E2E_BACKEND_HOSTPORT;
if (!backend) {
  console.error("E2E_BACKEND_HOSTPORT is required.");
  process.exit(2);
}

const buildEnv = { ...process.env, NODE_ENV: "production" };
delete buildEnv.BACKEND_INTERNAL_URL;
delete buildEnv.NEXT_PUBLIC_API_BASE_URL;
const build = spawnSync(process.execPath, [nextBin, "build"], { cwd: root, env: buildEnv, stdio: "inherit" });
if (build.status !== 0) process.exit(build.status ?? 1);

const server = spawn(process.execPath, [nextBin, "start", "--port", "3000"], {
  cwd: root,
  env: { ...process.env, NODE_ENV: "production", BACKEND_INTERNAL_URL: backend },
  stdio: "inherit",
});
const stop = () => {
  if (server.exitCode === null) server.kill();
};
for (const signal of ["SIGINT", "SIGTERM", "SIGBREAK", "SIGHUP"]) {
  process.on(signal, () => {
    stop();
    process.exit(0);
  });
}
process.on("exit", stop);
server.on("exit", (code) => process.exit(code ?? 0));

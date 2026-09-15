#!/usr/bin/env node
/**
 * Verify the same-origin /api proxy in a real production build (`next build` must already have
 * run, ideally with BACKEND_INTERNAL_URL unset).
 *
 * 1. The routes manifest has no rewrites, so no backend address was captured at build time.
 * 2. No client (static) chunk contains a backend address or the variable name.
 * 3. `next start` with BACKEND_INTERNAL_URL=<host:port> (Render hostport form, no scheme) proxies
 *    login cookies, the CSRF header, a POST body, a status code and a streamed download to a
 *    local fake backend.
 * 4. `next start` with BACKEND_INTERNAL_URL=hpip-api:10000 never reaches localhost: a sentinel
 *    listening on 127.0.0.1:8000 receives nothing and the proxy answers 502 backend_unavailable.
 * 5. `next start` without BACKEND_INTERNAL_URL fails closed with 500 proxy_misconfigured.
 *
 * Prints a JSON evidence summary and exits non-zero on any failure. Every process it starts is
 * stopped before it exits.
 */
import { spawn } from "node:child_process";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { createServer } from "node:http";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const nextDir = path.join(root, ".next");
const nextBin = path.join(root, "node_modules", "next", "dist", "bin", "next");
const evidence = {};
const children = new Set();
const servers = new Set();

function fail(message) {
  throw new Error(message);
}

function walk(dir) {
  return readdirSync(dir).flatMap((name) => {
    const full = path.join(dir, name);
    return statSync(full).isDirectory() ? walk(full) : [full];
  });
}

function staticChecks() {
  if (!existsSync(path.join(nextDir, "BUILD_ID"))) fail("No production build found; run `npm run build` first.");
  const manifest = JSON.parse(readFileSync(path.join(nextDir, "routes-manifest.json"), "utf8"));
  const rewrites = manifest.rewrites ?? [];
  const list = Array.isArray(rewrites)
    ? rewrites
    : [...(rewrites.beforeFiles ?? []), ...(rewrites.afterFiles ?? []), ...(rewrites.fallback ?? [])];
  evidence.routes_manifest_rewrites = list.length;
  if (list.length) fail(`routes-manifest.json contains rewrites: ${JSON.stringify(list)}`);
  const dynamicRoutes = (manifest.dynamicRoutes ?? []).map((item) => item.page);
  evidence.api_route_is_dynamic = dynamicRoutes.includes("/api/[...path]");
  if (!evidence.api_route_is_dynamic) fail("The /api/[...path] route handler is missing from the build.");
  const forbidden = [/localhost:8000/, /127\.0\.0\.1:80(00|10)/, /hpip-api/, /BACKEND_INTERNAL_URL/, /NEXT_PUBLIC_API_BASE_URL/];
  const clientFiles = walk(path.join(nextDir, "static")).filter((file) => file.endsWith(".js"));
  const offenders = [];
  for (const file of clientFiles) {
    const text = readFileSync(file, "utf8");
    for (const pattern of forbidden) {
      if (pattern.test(text)) offenders.push(`${path.relative(root, file)} matches ${pattern}`);
    }
  }
  evidence.client_chunks_scanned = clientFiles.length;
  evidence.client_chunks_with_backend_address = offenders.length;
  if (offenders.length) fail(`Client bundle carries a backend address:\n${offenders.join("\n")}`);
}

function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const { port } = server.address();
      server.close(() => resolve(port));
    });
  });
}

function portIsFree(port) {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.once("error", () => resolve(false));
    server.listen(port, "127.0.0.1", () => server.close(() => resolve(true)));
  });
}

function listen(handler, port = 0) {
  return new Promise((resolve) => {
    const server = createServer(handler);
    servers.add(server);
    server.listen(port, "127.0.0.1", () => resolve(server));
  });
}

async function startNext(backend) {
  const port = await freePort();
  const env = { ...process.env, NODE_ENV: "production", PORT: String(port) };
  delete env.BACKEND_INTERNAL_URL;
  if (backend !== undefined) env.BACKEND_INTERNAL_URL = backend;
  const child = spawn(process.execPath, [nextBin, "start", "--port", String(port), "--hostname", "127.0.0.1"], {
    cwd: root,
    env,
    stdio: ["ignore", "pipe", "pipe"],
  });
  children.add(child);
  let output = "";
  child.stdout.on("data", (chunk) => (output += chunk));
  child.stderr.on("data", (chunk) => (output += chunk));
  const base = `http://127.0.0.1:${port}`;
  const deadline = Date.now() + 90_000;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) fail(`next start exited early:\n${output}`);
    try {
      const response = await fetch(`${base}/login`, { redirect: "manual" });
      if (response.status < 500) return { child, base, output: () => output };
    } catch {
      // not listening yet
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  fail(`next start did not become ready:\n${output}`);
}

async function stop(child) {
  if (child.exitCode !== null) return;
  await new Promise((resolve) => {
    child.once("exit", resolve);
    child.kill();
    setTimeout(() => {
      if (child.exitCode === null) child.kill("SIGKILL");
    }, 5000);
  });
  children.delete(child);
}

async function runtimeChecks() {
  const download = Buffer.alloc(2 * 1024 * 1024, 5);
  const received = [];
  const fake = await listen((request, response) => {
    const chunks = [];
    request.on("data", (chunk) => chunks.push(chunk));
    request.on("end", () => {
      received.push({
        method: request.method,
        url: request.url,
        csrf: request.headers["x-csrf-token"] ?? null,
        cookie: request.headers.cookie ?? null,
        body: Buffer.concat(chunks).toString("utf8"),
      });
      if (request.url === "/auth/login") {
        response.writeHead(200, {
          "content-type": "application/json",
          "set-cookie": ["hpip_session=s1; Path=/; HttpOnly; SameSite=Lax", "hpip_csrf=c1; Path=/; SameSite=Lax"],
        });
        return response.end('{"ok":true}');
      }
      if (request.url === "/exports/jobs/j1/download") {
        response.writeHead(200, { "content-type": "application/octet-stream" });
        return response.end(download);
      }
      response.writeHead(409, { "content-type": "application/json" });
      response.end('{"detail":{"code":"export_not_ready"}}');
    });
  });
  const hostport = `127.0.0.1:${fake.address().port}`;

  const first = await startNext(hostport);
  try {
    const login = await fetch(`${first.base}/api/auth/login`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ username: "fake", password: "fake" }),
    });
    const cookies = login.headers.getSetCookie();
    if (login.status !== 200 || cookies.length !== 2) fail(`login proxy failed: ${login.status} ${cookies}`);
    const post = await fetch(`${first.base}/api/exports/excel`, {
      method: "POST",
      headers: { "content-type": "application/json", "x-csrf-token": "c1", cookie: "hpip_session=s1; hpip_csrf=c1" },
      body: '{"x":1}',
    });
    if (post.status !== 409) fail(`status code not preserved: ${post.status}`);
    const file = Buffer.from(
      await (
        await fetch(`${first.base}/api/exports/jobs/j1/download`, {
          method: "POST",
          headers: { "x-csrf-token": "c1", cookie: "hpip_session=s1; hpip_csrf=c1" },
        })
      ).arrayBuffer(),
    );
    if (!file.equals(download)) fail("download bytes differ");
    const csrfPost = received.find((item) => item.url === "/exports/excel");
    if (!csrfPost || csrfPost.csrf !== "c1" || csrfPost.cookie !== "hpip_session=s1; hpip_csrf=c1" || csrfPost.body !== '{"x":1}') {
      fail(`CSRF POST not forwarded intact: ${JSON.stringify(csrfPost)}`);
    }
    evidence.hostport_input = hostport;
    evidence.hostport_backend_requests = received.map((item) => `${item.method} ${item.url}`);
    evidence.set_cookie_headers_returned = cookies.length;
    evidence.download_bytes = file.length;
  } finally {
    await stop(first.child);
  }

  const sentinelHits = [];
  const sentinelPortFree = await portIsFree(8000);
  if (sentinelPortFree) {
    await listen((request, response) => {
      sentinelHits.push(request.url);
      response.writeHead(200);
      response.end("sentinel");
    }, 8000);
  }
  const second = await startNext("hpip-api:10000");
  try {
    const response = await fetch(`${second.base}/api/health`);
    const body = await response.text();
    evidence.render_hostport_input = "hpip-api:10000";
    evidence.render_hostport_status = response.status;
    evidence.render_hostport_body_code = JSON.parse(body).detail.code;
    evidence.localhost_8000_sentinel = sentinelPortFree ? "listening" : "port busy, sentinel skipped";
    evidence.localhost_8000_requests = sentinelHits.length;
    if (response.status !== 502 || evidence.render_hostport_body_code !== "backend_unavailable") {
      fail(`unexpected response for an unreachable Render hostport: ${response.status} ${body}`);
    }
    if (/hpip-api|10000|ENOTFOUND|EAI_AGAIN/.test(body)) fail("proxy error leaked the backend address");
    if (sentinelHits.length) fail("the proxy fell back to localhost:8000");
  } finally {
    await stop(second.child);
  }

  const third = await startNext(undefined);
  try {
    const response = await fetch(`${third.base}/api/health`);
    evidence.unset_target_status = response.status;
    evidence.unset_target_code = (await response.json()).detail.code;
    if (response.status !== 500 || evidence.unset_target_code !== "proxy_misconfigured") {
      fail("an unset BACKEND_INTERNAL_URL did not fail closed");
    }
    if (sentinelHits.length) fail("the proxy fell back to localhost:8000 without a target");
  } finally {
    await stop(third.child);
  }
}

async function cleanup() {
  for (const child of children) await stop(child);
  for (const server of servers) await new Promise((resolve) => server.close(resolve));
}

try {
  staticChecks();
  await runtimeChecks();
  evidence.result = "passed";
  console.log(JSON.stringify(evidence, null, 2));
  await cleanup();
  process.exit(0);
} catch (error) {
  evidence.result = "failed";
  evidence.error = String(error?.message ?? error);
  console.error(JSON.stringify(evidence, null, 2));
  await cleanup();
  process.exit(1);
}

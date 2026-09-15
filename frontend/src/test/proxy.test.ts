// @vitest-environment node
import { createServer, type IncomingMessage, type Server, type ServerResponse } from "node:http";
import type { AddressInfo } from "node:net";
import { readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

import { BackendTargetError, resolveBackendTarget } from "@/lib/server/backendTarget";
import { proxyRequest, upstreamUrl } from "@/lib/server/proxy";

describe("backend target resolution", () => {
  it.each([
    ["hpip-api:10000", "http://hpip-api:10000"],
    ["hpip-api-abcd:10000", "http://hpip-api-abcd:10000"],
    ["http://api:8000", "http://api:8000"],
    ["http://api:8000/", "http://api:8000"],
    ["https://api.internal.example///", "https://api.internal.example"],
    ["http://api:8000/prefix/", "http://api:8000/prefix"],
    ["127.0.0.1:8010", "http://127.0.0.1:8010"],
    ["  api  ", "http://api"],
  ])("%s -> %s", (raw, expected) => {
    expect(resolveBackendTarget(raw, "production")).toBe(expected);
  });

  it("never falls back to localhost in production", () => {
    expect(() => resolveBackendTarget(undefined, "production")).toThrow(BackendTargetError);
    expect(() => resolveBackendTarget("", "production")).toThrow(BackendTargetError);
    expect(resolveBackendTarget("hpip-api:10000", "production")).not.toMatch(/localhost|127\.0\.0\.1/);
  });

  it("uses the local development backend only outside production", () => {
    expect(resolveBackendTarget(undefined, "development")).toBe("http://127.0.0.1:8000");
  });

  it.each([
    "ftp://api:21",
    "javascript:alert(1)",
    "file:///etc/passwd",
    "http://user:secret@api:8000",
    "http://api:8000/?token=abc",
    "http://api:8000/#frag",
    "api host:8000",
    "api:port",
    "//api:8000",
  ])("rejects %s", (raw) => {
    expect(() => resolveBackendTarget(raw, "production")).toThrow(BackendTargetError);
  });
});

describe("upstream url construction", () => {
  it("encodes segments and keeps the query string", () => {
    expect(upstreamUrl("http://api:8000", ["exports", "jobs", "a b"], "?limit=5")).toBe(
      "http://api:8000/exports/jobs/a%20b?limit=5",
    );
  });

  it.each([[[".."]], [["exports", "."]], [["a/b"]], [["a\\b"]]])("refuses traversal %j", (segments) => {
    expect(upstreamUrl("http://api:8000", segments, "")).toBeNull();
  });
});

type Seen = { method: string; url: string; headers: IncomingMessage["headers"]; body: string };

describe("proxy request forwarding against a real HTTP backend", () => {
  let server: Server;
  let hostport: string;
  const seen: Seen[] = [];
  const download = Buffer.alloc(1024 * 1024 * 3, 7);

  beforeAll(async () => {
    server = createServer((request: IncomingMessage, response: ServerResponse) => {
      const chunks: Buffer[] = [];
      request.on("data", (chunk) => chunks.push(chunk));
      request.on("end", () => {
        const body = Buffer.concat(chunks).toString("utf8");
        seen.push({ method: request.method ?? "", url: request.url ?? "", headers: request.headers, body });
        if (request.url === "/auth/login") {
          response.writeHead(200, {
            "content-type": "application/json",
            "set-cookie": [
              "hpip_session=abc; Path=/; HttpOnly; SameSite=Lax",
              "hpip_csrf=xyz; Path=/; SameSite=Lax",
            ],
            connection: "keep-alive",
          });
          response.end(JSON.stringify({ ok: true }));
          return;
        }
        if (request.url?.startsWith("/exports/jobs/job-1/download")) {
          response.writeHead(200, {
            "content-type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "content-disposition": 'attachment; filename="report.xlsx"',
          });
          // Streamed in chunks, like a large export.
          let offset = 0;
          const pump = () => {
            while (offset < download.length) {
              const next = download.subarray(offset, offset + 65536);
              offset += next.length;
              if (!response.write(next)) {
                response.once("drain", pump);
                return;
              }
            }
            response.end();
          };
          pump();
          return;
        }
        if (request.url === "/forbidden") {
          response.writeHead(403, { "content-type": "application/json" });
          response.end(JSON.stringify({ detail: { code: "csrf_failed" } }));
          return;
        }
        response.writeHead(201, { "content-type": "application/json" });
        response.end(JSON.stringify({ echoed: body }));
      });
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    hostport = `127.0.0.1:${(server.address() as AddressInfo).port}`;
  });

  afterAll(async () => {
    await new Promise<void>((resolve) => server.close(() => resolve()));
  });

  const env = () => ({ BACKEND_INTERNAL_URL: hostport, NODE_ENV: "production" });

  it("forwards method, body, cookies and the CSRF header, and returns every Set-Cookie", async () => {
    const response = await proxyRequest(
      new Request("http://localhost:3000/api/auth/login", {
        method: "POST",
        headers: { "content-type": "application/json", cookie: "existing=1", "x-csrf-token": "token-123" },
        body: JSON.stringify({ username: "u", password: "p" }),
      }),
      ["auth", "login"],
      env(),
    );
    expect(response.status).toBe(200);
    expect(response.headers.getSetCookie()).toEqual([
      "hpip_session=abc; Path=/; HttpOnly; SameSite=Lax",
      "hpip_csrf=xyz; Path=/; SameSite=Lax",
    ]);
    expect(response.headers.get("connection")).toBeNull();
    const request = seen.at(-1)!;
    expect(request.method).toBe("POST");
    expect(JSON.parse(request.body)).toEqual({ username: "u", password: "p" });
    expect(request.headers.cookie).toBe("existing=1");
    expect(request.headers["x-csrf-token"]).toBe("token-123");
    expect(request.headers["x-forwarded-host"]).toBe("localhost:3000");
    expect(request.headers.host).toBe(hostport);
  });

  it("preserves status codes and error bodies", async () => {
    const response = await proxyRequest(
      new Request("http://localhost:3000/api/forbidden", { method: "DELETE" }),
      ["forbidden"],
      env(),
    );
    expect(response.status).toBe(403);
    expect(await response.json()).toEqual({ detail: { code: "csrf_failed" } });
  });

  it("streams downloads byte for byte with their headers", async () => {
    const response = await proxyRequest(
      new Request("http://localhost:3000/api/exports/jobs/job-1/download?x=1", { method: "POST" }),
      ["exports", "jobs", "job-1", "download"],
      env(),
    );
    expect(response.status).toBe(200);
    expect(response.headers.get("content-disposition")).toBe('attachment; filename="report.xlsx"');
    const bytes = Buffer.from(await response.arrayBuffer());
    expect(bytes.length).toBe(download.length);
    expect(bytes.equals(download)).toBe(true);
    expect(seen.at(-1)!.url).toBe("/exports/jobs/job-1/download?x=1");
  });

  it("fails safely without naming the backend when it is unreachable", async () => {
    const response = await proxyRequest(
      new Request("http://localhost:3000/api/health"),
      ["health"],
      { BACKEND_INTERNAL_URL: "127.0.0.1:1", NODE_ENV: "production" },
    );
    expect(response.status).toBe(502);
    const text = await response.text();
    expect(JSON.parse(text).detail.code).toBe("backend_unavailable");
    expect(text).not.toMatch(/127\.0\.0\.1|ECONNREFUSED|:1\b/);
  });

  it("fails closed when the target is missing or invalid in production", async () => {
    for (const value of [undefined, "ftp://api", "http://user:pw@api"]) {
      const response = await proxyRequest(new Request("http://localhost:3000/api/health"), ["health"], {
        BACKEND_INTERNAL_URL: value,
        NODE_ENV: "production",
      });
      expect(response.status).toBe(500);
      const text = await response.text();
      expect(JSON.parse(text).detail.code).toBe("proxy_misconfigured");
      expect(text).not.toMatch(/user|pw|ftp/);
    }
  });
});

describe("client code never carries a backend address", () => {
  const src = path.resolve(__dirname, "..");
  const files = (dir: string): string[] =>
    readdirSync(dir).flatMap((name) => {
      const full = path.join(dir, name);
      return statSync(full).isDirectory() ? files(full) : [full];
    });

  it("only the server route imports the proxy modules", () => {
    const importers = files(src)
      .filter((file) => /\.(ts|tsx)$/.test(file) && !file.includes(`${path.sep}test${path.sep}`))
      .filter((file) => readFileSync(file, "utf8").includes("lib/server/"))
      .map((file) => path.relative(src, file).split(path.sep).join("/"));
    expect(importers).toEqual(["app/api/[...path]/route.ts"]);
  });

  it("the browser API client is fixed to /api", () => {
    const client = readFileSync(path.join(src, "lib", "api.ts"), "utf8");
    expect(client).toContain('const API_BASE = "/api";');
    expect(client).not.toMatch(/NEXT_PUBLIC_API_BASE_URL|BACKEND_INTERNAL_URL|localhost|127\.0\.0\.1/);
  });
});

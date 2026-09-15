import { BackendTargetError, resolveBackendTarget } from "./backendTarget";

/**
 * Same-origin API proxy used by `src/app/api/[...path]/route.ts`.
 *
 * - Forwards the method, query string, body (streamed), Cookie and X-CSRF-Token headers.
 * - Returns the backend status, body (streamed, so downloads are not buffered) and every
 *   Set-Cookie header individually, so the session and CSRF cookies land on this origin.
 * - Strips hop-by-hop headers in both directions and never forwards the browser's Host.
 * - Fails with a generic JSON error that names neither the backend host nor the cause.
 */

const HOP_BY_HOP = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
  "host",
  "content-length",
]);
// fetch() already decoded the body, so these would describe bytes the browser never receives.
const DECODED_RESPONSE_HEADERS = new Set(["content-encoding", "content-length"]);

export type ProxyEnvironment = {
  BACKEND_INTERNAL_URL?: string;
  NODE_ENV?: string;
};

type Fetch = typeof fetch;

function errorResponse(status: number, code: string, message: string): Response {
  return new Response(JSON.stringify({ detail: { code, message } }), {
    status,
    headers: { "content-type": "application/json", "cache-control": "no-store" },
  });
}

export function upstreamUrl(target: string, segments: string[], search: string): string | null {
  if (segments.some((segment) => segment === "." || segment === ".." || segment.includes("/") || segment.includes("\\"))) {
    return null;
  }
  const path = segments.map((segment) => encodeURIComponent(segment)).join("/");
  return `${target}/${path}${search}`;
}

function forwardedHeaders(request: Request): Headers {
  const headers = new Headers();
  request.headers.forEach((value, key) => {
    if (!HOP_BY_HOP.has(key.toLowerCase())) {
      headers.set(key, value);
    }
  });
  const url = new URL(request.url);
  headers.set("x-forwarded-host", url.host);
  headers.set("x-forwarded-proto", url.protocol.replace(":", ""));
  return headers;
}

function responseHeaders(upstream: Response): Headers {
  const headers = new Headers();
  upstream.headers.forEach((value, key) => {
    const name = key.toLowerCase();
    if (name === "set-cookie" || HOP_BY_HOP.has(name) || DECODED_RESPONSE_HEADERS.has(name)) {
      return;
    }
    headers.set(key, value);
  });
  // Multiple Set-Cookie headers must stay separate; joining them corrupts cookie attributes.
  const cookies = typeof upstream.headers.getSetCookie === "function" ? upstream.headers.getSetCookie() : [];
  for (const cookie of cookies) {
    headers.append("set-cookie", cookie);
  }
  return headers;
}

export async function proxyRequest(
  request: Request,
  segments: string[],
  env: ProxyEnvironment = process.env,
  fetchImpl: Fetch = fetch,
): Promise<Response> {
  let target: string;
  try {
    target = resolveBackendTarget(env.BACKEND_INTERNAL_URL, env.NODE_ENV);
  } catch (error) {
    if (error instanceof BackendTargetError) {
      console.error(`[api-proxy] ${error.message}`);
      return errorResponse(500, "proxy_misconfigured", "The analytics service is not configured.");
    }
    throw error;
  }
  const url = upstreamUrl(target, segments, new URL(request.url).search);
  if (url === null) {
    return errorResponse(400, "invalid_path", "The requested path is not allowed.");
  }
  const method = request.method.toUpperCase();
  const hasBody = !["GET", "HEAD"].includes(method);
  let upstream: Response;
  try {
    upstream = await fetchImpl(url, {
      method,
      headers: forwardedHeaders(request),
      body: hasBody ? request.body : undefined,
      redirect: "manual",
      signal: request.signal,
      cache: "no-store",
      // Required by Node's fetch to stream a request body.
      ...(hasBody ? { duplex: "half" } : {}),
    } as RequestInit);
  } catch {
    // Never echo the backend address or the network error to the browser.
    console.error("[api-proxy] backend request failed");
    return errorResponse(502, "backend_unavailable", "The analytics service is temporarily unavailable.");
  }
  return new Response(method === "HEAD" ? null : upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: responseHeaders(upstream),
  });
}

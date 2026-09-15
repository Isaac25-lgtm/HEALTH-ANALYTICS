/**
 * Server-only resolution of the backend the same-origin `/api` proxy forwards to.
 *
 * BACKEND_INTERNAL_URL is read at request time, never at build time, so nothing about the
 * backend is compiled into the production bundle and one image works in every environment.
 * Render's `hostport` property is a bare `host:port` (for example `hpip-api:10000`), so a value
 * without a scheme is treated as plain HTTP on the private network.
 *
 * Accepted:  http(s)://host[:port][/path], host:port, host
 * Rejected:  any other scheme, embedded credentials, a query or fragment, whitespace, empty
 *            values in production.
 */

export class BackendTargetError extends Error {
  readonly code = "backend_target_invalid";
}

const SCHEME = /^[A-Za-z][A-Za-z0-9+.-]*:\/\//;
const BARE_HOST = /^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?(:\d{1,5})?$|^\[[0-9A-Fa-f:.]+\](:\d{1,5})?$/;
export const DEVELOPMENT_BACKEND = "http://127.0.0.1:8000";

export function resolveBackendTarget(raw: string | undefined, nodeEnv: string | undefined = process.env.NODE_ENV): string {
  const value = (raw ?? "").trim();
  if (!value) {
    if (nodeEnv === "production") {
      throw new BackendTargetError("BACKEND_INTERNAL_URL is required in production.");
    }
    return DEVELOPMENT_BACKEND;
  }
  if (/\s/.test(value)) {
    throw new BackendTargetError("BACKEND_INTERNAL_URL must not contain whitespace.");
  }
  let candidate = value;
  if (!SCHEME.test(value)) {
    if (!BARE_HOST.test(value)) {
      throw new BackendTargetError("BACKEND_INTERNAL_URL must be an http(s) URL or host:port.");
    }
    candidate = `http://${value}`;
  }
  let parsed: URL;
  try {
    parsed = new URL(candidate);
  } catch {
    throw new BackendTargetError("BACKEND_INTERNAL_URL is not a valid URL.");
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new BackendTargetError("BACKEND_INTERNAL_URL must use http or https.");
  }
  if (parsed.username || parsed.password) {
    throw new BackendTargetError("BACKEND_INTERNAL_URL must not contain credentials.");
  }
  if (parsed.search || parsed.hash || candidate.includes("?") || candidate.includes("#")) {
    throw new BackendTargetError("BACKEND_INTERNAL_URL must not contain a query or fragment.");
  }
  if (!parsed.hostname) {
    throw new BackendTargetError("BACKEND_INTERNAL_URL has no host.");
  }
  const path = parsed.pathname.replace(/\/+$/, "");
  return `${parsed.protocol}//${parsed.host}${path}`;
}

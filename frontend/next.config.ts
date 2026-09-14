import type { NextConfig } from "next";

/**
 * The browser never talks to the backend hostname directly. `/api/*` is rewritten
 * server-side to BACKEND_INTERNAL_URL, so:
 *   - the session cookie and the readable CSRF cookie stay on the frontend origin;
 *   - the backend can stay on a private Render hostname;
 *   - no wide cookie domain is needed for a provider-shared domain.
 */
const backend = process.env.BACKEND_INTERNAL_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  // Standard `.next` output. Do not switch distDir to work around locked artifacts;
  // see docs/architecture/LOCAL_DEVELOPMENT.md ("Locked build output on Windows").
  transpilePackages: ["maplibre-gl"],
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${backend}/:path*`,
      },
    ];
  },
};

export default nextConfig;

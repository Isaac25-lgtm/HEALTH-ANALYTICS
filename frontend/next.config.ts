import type { NextConfig } from "next";

/**
 * The browser never talks to the backend hostname directly. It calls same-origin `/api/*`,
 * handled at request time by `src/app/api/[...path]/route.ts`, which forwards to
 * BACKEND_INTERNAL_URL. There are deliberately no build-time rewrites: a rewrite would bake
 * whatever backend address existed during `next build` into the routes manifest.
 */
const nextConfig: NextConfig = {
  // Standard `.next` output. Do not switch distDir to work around locked artifacts;
  // see docs/architecture/LOCAL_DEVELOPMENT.md ("Locked build output on Windows").
  transpilePackages: ["maplibre-gl"],
};

export default nextConfig;

import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Standard `.next` output. Do not switch distDir to work around locked artifacts;
  // see docs/architecture/LOCAL_DEVELOPMENT.md ("Locked build output on Windows").
  transpilePackages: ["maplibre-gl"],
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://127.0.0.1:8000/:path*",
      },
    ];
  },
};

export default nextConfig;

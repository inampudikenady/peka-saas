import type { NextConfig } from "next";

const backend = process.env.PEKA_BACKEND_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  async rewrites() {
    return [
      { source: "/health", destination: `${backend}/health` },
      { source: "/api/:path*", destination: `${backend}/api/:path*` },
      { source: "/t/:slug/api/:path*", destination: `${backend}/t/:slug/api/:path*` },
    ];
  },
};

export default nextConfig;

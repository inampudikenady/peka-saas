import type { NextConfig } from "next";

const backend = process.env.PEKA_BACKEND_URL ?? "http://127.0.0.1:8000";
const proxyTimeout = Number(process.env.PEKA_PROXY_TIMEOUT_MS ?? 180_000);

const nextConfig: NextConfig = {
  output: "standalone",
  experimental: {
    // Next's rewrite proxy otherwise aborts an idle upstream request after 30s.
    // The backend also sends SSE keepalives, but this must remain longer than the
    // configured model timeout for slow local Ollama generations.
    proxyTimeout,
  },
  async rewrites() {
    return [
      { source: "/health", destination: `${backend}/health` },
      { source: "/api/:path*", destination: `${backend}/api/:path*` },
      { source: "/t/:slug/api/:path*", destination: `${backend}/t/:slug/api/:path*` },
    ];
  },
};

export default nextConfig;

import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  experimental: {
    // Docker Desktop became unreliable while Next spawned one worker per host CPU.
    // Two workers keep page generation fast without starving API/PostgreSQL.
    cpus: 2,
  },
  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: "http://api:8000/api/v1/:path*",
      },
    ];
  },
};

export default nextConfig;


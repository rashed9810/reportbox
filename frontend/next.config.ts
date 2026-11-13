import type { NextConfig } from "next";

// The website calls the API on its own domain (/api/...). In development, Next.js forwards those
// calls to the backend. In production, the Caddy proxy sends /api straight to the backend.
const backend = process.env.BACKEND_URL || "http://localhost:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${backend}/api/:path*` },
      { source: "/fhir/:path*", destination: `${backend}/fhir/:path*` },
    ];
  },
};

export default nextConfig;

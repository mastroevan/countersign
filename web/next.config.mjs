/** @type {import('next').NextConfig} */
const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

const nextConfig = {
  reactStrictMode: false,
  skipTrailingSlashRedirect: true,
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${BACKEND_URL}/api/:path*`,
      },
      {
        source: "/verifications/:path*",
        destination: `${BACKEND_URL}/verifications/:path*`,
      },
      {
        source: "/verify",
        destination: `${BACKEND_URL}/verify`,
      },
      {
        source: "/webhooks/:path*",
        destination: `${BACKEND_URL}/webhooks/:path*`,
      },
      {
        source: "/mcp/",
        destination: `${BACKEND_URL}/mcp/`,
      },
      {
        source: "/mcp/:path*",
        destination: `${BACKEND_URL}/mcp/:path*`,
      },
      {
        source: "/mcp",
        destination: `${BACKEND_URL}/mcp/`,
      },
      {
        source: "/healthz",
        destination: `${BACKEND_URL}/healthz`,
      },
    ];
  },
};

export default nextConfig;

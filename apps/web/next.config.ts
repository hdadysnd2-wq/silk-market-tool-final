import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

const nextConfig: NextConfig = {
  reactStrictMode: true,
  async rewrites() {
    // Proxy API calls to the FastAPI backend so the browser talks to one origin.
    const apiBase = process.env.API_PROXY_TARGET ?? "http://localhost:8000";
    return [{ source: "/api/:path*", destination: `${apiBase}/api/:path*` }];
  },
};

export default withNextIntl(nextConfig);

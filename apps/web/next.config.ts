import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

// Baseline security headers. The Content-Security-Policy lives in
// src/middleware.ts, not here: it carries a per-request script nonce, which a
// static header cannot. Everything below is request-independent. frame-ancestors
// is enforced by the middleware CSP; X-Frame-Options stays as the legacy
// belt-and-suspenders for it.
const SECURITY_HEADERS = [
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
  { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains; preload" },
];

const nextConfig: NextConfig = {
  reactStrictMode: true,
  async headers() {
    return [{ source: "/:path*", headers: SECURITY_HEADERS }];
  },
  async rewrites() {
    // Proxy backend calls to FastAPI so the browser talks to one origin. Scoped
    // to /api/v1 so the Next session route handlers under /api/session/* (which
    // set the httpOnly cookie) are served locally, not proxied.
    const apiBase = process.env.API_PROXY_TARGET ?? "http://localhost:8000";
    return [{ source: "/api/v1/:path*", destination: `${apiBase}/api/v1/:path*` }];
  },
};

export default withNextIntl(nextConfig);

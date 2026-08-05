import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

// Baseline security headers. The API is same-origin (proxied via rewrites), so
// connect-src 'self' suffices. 'unsafe-inline' is kept for script/style because
// the App Router injects inline bootstrap scripts without a nonce; nonce-based
// hardening is a follow-up. 'unsafe-eval' is added in DEV ONLY — `next dev`
// (used by the Playwright e2e) relies on eval for React Fast Refresh/HMR; the
// production bundle does not, so prod keeps the stricter policy. frame-ancestors
// 'none' + X-Frame-Options block clickjacking; img-src allows https for
// cross-origin storage (presigned URLs).
const isDev = process.env.NODE_ENV !== "production";
const scriptSrc = isDev
  ? "script-src 'self' 'unsafe-inline' 'unsafe-eval'"
  : "script-src 'self' 'unsafe-inline'";
const CSP = [
  "default-src 'self'",
  scriptSrc,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob: https:",
  "font-src 'self' data:",
  "connect-src 'self'",
  "frame-ancestors 'none'",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
].join("; ");

const SECURITY_HEADERS = [
  { key: "Content-Security-Policy", value: CSP },
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

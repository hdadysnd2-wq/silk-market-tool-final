import type { NextRequest } from "next/server";
import createMiddleware from "next-intl/middleware";
import { routing } from "./i18n/routing";

const handleI18nRouting = createMiddleware(routing);

// Per-request CSP nonce (Wave 2). The static config carried
// `script-src 'unsafe-inline'`, which neutralizes CSP against exactly the
// injected-script attacks it exists for. A nonce must differ per request, so
// the policy moves from next.config.ts to middleware: the nonce travels to the
// renderer via the x-nonce / Content-Security-Policy *request* headers (Next
// stamps it onto its inline bootstrap scripts), and the same policy is set on
// the response. 'unsafe-eval' stays in dev only — `next dev` (used by the
// Playwright e2e) needs eval for React Fast Refresh; the production bundle
// does not. style-src keeps 'unsafe-inline' (Tailwind/React inline styles —
// out of scope here). Non-CSP security headers remain in next.config.ts.
function buildCsp(nonce: string): string {
  const isDev = process.env.NODE_ENV !== "production";
  const scriptSrc = isDev
    ? `script-src 'self' 'nonce-${nonce}' 'unsafe-eval'`
    : `script-src 'self' 'nonce-${nonce}'`;
  return [
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
}

export default function middleware(request: NextRequest) {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  const nonce = btoa(String.fromCharCode(...bytes));
  const csp = buildCsp(nonce);

  // Mutating the incoming request headers before the i18n middleware runs is
  // what forwards them into the render (next-intl passes request.headers to
  // NextResponse.rewrite/next).
  request.headers.set("x-nonce", nonce);
  request.headers.set("Content-Security-Policy", csp);

  const response = handleI18nRouting(request);
  response.headers.set("Content-Security-Policy", csp);
  return response;
}

export const config = {
  // Match everything except API routes, Next internals, and static files.
  matcher: ["/((?!api|_next|_vercel|.*\\..*).*)"],
};

// Server-side auth helpers for the (app)/(admin) layouts and the session route
// handlers. `verifyToken` checks the JWT's HS256 signature against the shared
// SECRET_KEY — the client never sees or is trusted with the token (C2). This
// module is server-only (it imports node:crypto); do not import it from a
// client component (it imports node:crypto).
import { createHmac, timingSafeEqual } from "node:crypto";

interface JwtPayload {
  role?: string;
  sub?: string;
  exp?: number;
}

function b64urlToJson(part: string): Record<string, unknown> {
  return JSON.parse(Buffer.from(part, "base64url").toString("utf-8"));
}

/**
 * Verify a JWT's signature and expiry with the shared secret, returning the
 * payload or null. An unsigned/tampered/expired token — or a missing secret —
 * yields null so the caller redirects to login. This replaces the previous
 * unverified base64 decode (CRITICAL-2 / the layouts must not trust a forgeable
 * token).
 */
export function verifyToken(token: string | undefined | null): JwtPayload | null {
  if (!token) return null;
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  const [header, payload, signature] = parts;
  const secret = process.env.SECRET_KEY;
  if (!secret) return null;
  const expected = createHmac("sha256", secret).update(`${header}.${payload}`).digest("base64url");
  const got = Buffer.from(signature);
  const want = Buffer.from(expected);
  if (got.length !== want.length || !timingSafeEqual(got, want)) return null;
  try {
    const claims = b64urlToJson(payload) as JwtPayload;
    if (typeof claims.exp === "number" && claims.exp * 1000 <= Date.now()) return null;
    return claims;
  } catch {
    return null;
  }
}

/** Decode the role without verifying — only for a token we just minted ourselves. */
export function decodeRole(token: string): string | null {
  try {
    const part = token.split(".")[1];
    if (!part) return null;
    return (b64urlToJson(part) as JwtPayload).role ?? null;
  } catch {
    return null;
  }
}

export function isStaffRole(role: string | null | undefined): boolean {
  return role === "admin" || role === "analyst";
}

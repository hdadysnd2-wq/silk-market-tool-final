// Shared session-cookie contract for the /api/session/* route handlers.
// Server-only (route handlers); client JS never touches the token (C2).

export const SESSION_COOKIE = "silk_token";
export const SESSION_MAX_AGE = 60 * 60 * 12; // 12h, matches the access-token TTL

/**
 * The `Secure` attribute must match how the app is actually served: browsers
 * silently drop a Secure cookie set over plain HTTP (except on localhost),
 * which turns login into a redirect loop with no error. Default follows
 * NODE_ENV; a deployment behind plain HTTP (or a TLS-terminating proxy quirk)
 * can override with COOKIE_SECURE=0 / =1 explicitly.
 */
export function sessionCookieOptions() {
  const override = process.env.COOKIE_SECURE;
  const secure =
    override === undefined || override === ""
      ? process.env.NODE_ENV === "production"
      : override === "1" || override.toLowerCase() === "true";
  return {
    httpOnly: true as const,
    sameSite: "lax" as const,
    secure,
    path: "/",
    maxAge: SESSION_MAX_AGE,
  };
}

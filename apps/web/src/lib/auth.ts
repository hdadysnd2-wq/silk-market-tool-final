// Role helpers shared by the (app) and (admin) server layouts. The JWT is only
// *decoded* here for routing/nav decisions — never trusted for authorization,
// which the API enforces on every request. Works server-side (Buffer) and in
// the browser (atob), and tolerates base64url payloads.

interface JwtPayload {
  role?: string;
}

export function decodeRole(token: string): string | null {
  try {
    const part = token.split(".")[1];
    if (!part) return null;
    const b64 = part.replace(/-/g, "+").replace(/_/g, "/");
    const json =
      typeof atob !== "undefined" ? atob(b64) : Buffer.from(b64, "base64").toString("utf-8");
    return (JSON.parse(json) as JwtPayload).role ?? null;
  } catch {
    return null;
  }
}

export function isStaffRole(role: string | null): boolean {
  return role === "admin" || role === "analyst";
}

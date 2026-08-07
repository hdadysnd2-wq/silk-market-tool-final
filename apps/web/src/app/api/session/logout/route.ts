import { NextResponse, type NextRequest } from "next/server";
import { SESSION_COOKIE } from "@/lib/session";

// The API base the server talks to (never exposed to the browser). Same value
// the /api/v1 rewrite uses.
const API = process.env.API_PROXY_TARGET ?? "http://localhost:8000";

// Clears the httpOnly session cookie AND revokes the token server-side (jti
// denylist) — without the revoke, the 12h JWT would outlive the logout.
// POST-only so it can't be triggered by a cross-site <img>/navigation. The
// upstream call is best-effort: the cookie clear must never block on the API
// or Redis being down (the token then simply rides out its TTL, exactly the
// pre-revocation behavior).
export async function POST(req: NextRequest) {
  const token = req.cookies.get(SESSION_COOKIE)?.value;
  if (token) {
    await fetch(`${API}/api/v1/auth/logout`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    }).catch(() => undefined);
  }
  const res = NextResponse.json({ ok: true });
  res.cookies.set(SESSION_COOKIE, "", { httpOnly: true, path: "/", maxAge: 0 });
  return res;
}

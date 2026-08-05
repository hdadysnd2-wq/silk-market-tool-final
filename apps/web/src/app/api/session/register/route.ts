import { NextResponse, type NextRequest } from "next/server";
import { decodeRole, verifyToken } from "@/lib/auth";
import { SESSION_COOKIE, sessionCookieOptions } from "@/lib/session";

const API = process.env.API_PROXY_TARGET ?? "http://localhost:8000";

// Server-side register + auto-login: creates the account upstream and stores the
// returned token in the httpOnly session cookie (C2 — the client never holds it).
export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => null);
  if (!body) {
    return NextResponse.json({ detail: "Invalid request" }, { status: 400 });
  }
  const upstream = await fetch(`${API}/api/v1/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!upstream.ok) {
    const detail = await upstream.json().catch(() => ({}));
    return NextResponse.json(
      { detail: detail.detail ?? "Registration failed" },
      { status: upstream.status },
    );
  }
  const { access_token } = await upstream.json();
  // Same loud-failure guard as session/login: a SECRET_KEY missing/mismatch on
  // the web tier must surface as an error, not a silent redirect loop.
  if (!verifyToken(access_token)) {
    console.error(
      "session/register: upstream register succeeded but this web server cannot " +
        "verify the session token. SECRET_KEY is missing on the web service or " +
        "differs from the API's — set the identical value on api/worker/beat/web.",
    );
    return NextResponse.json(
      { detail: "Server misconfiguration: SECRET_KEY missing or mismatched on the web service" },
      { status: 500 },
    );
  }
  const res = NextResponse.json({ role: decodeRole(access_token) });
  res.cookies.set(SESSION_COOKIE, access_token, sessionCookieOptions());
  return res;
}

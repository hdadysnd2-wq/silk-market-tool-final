import { NextResponse, type NextRequest } from "next/server";
import { decodeRole, verifyToken } from "@/lib/auth";
import { SESSION_COOKIE, sessionCookieOptions } from "@/lib/session";

// The API base the server talks to (never exposed to the browser). Same value
// the /api/v1 rewrite uses.
const API = process.env.API_PROXY_TARGET ?? "http://localhost:8000";

// Server-side login: exchanges credentials for a token and stores it in an
// httpOnly cookie so client JS never touches it (C2 — CRITICAL-2). Returns only
// the role, for the post-login redirect.
export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => null);
  if (!body?.email || !body?.password) {
    return NextResponse.json({ detail: "Email and password required" }, { status: 400 });
  }
  const upstream = await fetch(`${API}/api/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: body.email, password: body.password }),
  });
  if (!upstream.ok) {
    const detail = await upstream.json().catch(() => ({}));
    return NextResponse.json({ detail: detail.detail ?? "Login failed" }, { status: upstream.status });
  }
  const { access_token } = await upstream.json();
  // Fail LOUDLY instead of looping: if this server can't verify the token it
  // just received (SECRET_KEY unset on the web service, or different from the
  // API's), every authenticated layout would bounce the user straight back to
  // /login with no error — the classic silent login loop. Surface it here.
  if (!verifyToken(access_token)) {
    console.error(
      "session/login: upstream login succeeded but this web server cannot verify " +
        "the session token. SECRET_KEY is missing on the web service or differs " +
        "from the API's — set the identical value on api/worker/beat/web.",
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

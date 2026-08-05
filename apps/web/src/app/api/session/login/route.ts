import { NextResponse, type NextRequest } from "next/server";
import { decodeRole } from "@/lib/auth";

// The API base the server talks to (never exposed to the browser). Same value
// the /api/v1 rewrite uses.
const API = process.env.API_PROXY_TARGET ?? "http://localhost:8000";
const SESSION_COOKIE = "silk_token";
const MAX_AGE = 60 * 60 * 12; // 12h, matches the access-token TTL

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
  const res = NextResponse.json({ role: decodeRole(access_token) });
  res.cookies.set(SESSION_COOKIE, access_token, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: MAX_AGE,
  });
  return res;
}

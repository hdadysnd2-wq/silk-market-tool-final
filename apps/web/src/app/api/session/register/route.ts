import { NextResponse, type NextRequest } from "next/server";
import { decodeRole } from "@/lib/auth";
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
  const res = NextResponse.json({ role: decodeRole(access_token) });
  res.cookies.set(SESSION_COOKIE, access_token, sessionCookieOptions());
  return res;
}

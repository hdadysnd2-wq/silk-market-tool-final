import { NextResponse } from "next/server";
import { SESSION_COOKIE } from "@/lib/session";

// Clears the httpOnly session cookie. POST-only so it can't be triggered by a
// cross-site <img>/navigation.
export async function POST() {
  const res = NextResponse.json({ ok: true });
  res.cookies.set(SESSION_COOKIE, "", { httpOnly: true, path: "/", maxAge: 0 });
  return res;
}

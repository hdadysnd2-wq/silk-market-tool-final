import { cookies } from "next/headers";
import { redirect } from "@/i18n/routing";
import { getLocale } from "next-intl/server";
import { AppShell } from "@/components/AppShell";
import { isStaffRole, verifyToken } from "@/lib/auth";

const SESSION_COOKIE = "silk_token";

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  const locale = await getLocale();
  // Verify the JWT signature (not just decode it) — a forged/expired token is
  // rejected to /login (C2 — CRITICAL-2).
  const claims = verifyToken(token);
  if (!claims) {
    redirect({ href: "/login", locale });
  }
  // Staff (factory_id NULL) have no tenant to scope to — the factory pages 400
  // for them. Send them to the dedicated admin console instead of rendering
  // blank tenant screens.
  if (isStaffRole(claims!.role)) {
    redirect({ href: "/admin", locale });
  }
  return <AppShell>{children}</AppShell>;
}

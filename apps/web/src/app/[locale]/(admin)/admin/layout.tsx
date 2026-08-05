import { cookies } from "next/headers";
import { getLocale } from "next-intl/server";
import { redirect } from "@/i18n/routing";
import { AdminShell } from "@/components/AdminShell";
import { isStaffRole, verifyToken } from "@/lib/auth";

const SESSION_COOKIE = "silk_token";

export default async function AdminLayout({ children }: { children: React.ReactNode }) {
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  const locale = await getLocale();
  // Verify the JWT signature server-side — a forged token cannot reach the
  // console (C2). The API also enforces staff-only on every /admin call.
  const claims = verifyToken(token);
  if (!claims) {
    redirect({ href: "/login", locale });
  }
  // Staff-only. Factory users have no place in the concierge console.
  if (!isStaffRole(claims!.role)) {
    redirect({ href: "/dashboard", locale });
  }
  return <AdminShell>{children}</AdminShell>;
}

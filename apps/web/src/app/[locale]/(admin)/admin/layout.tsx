import { cookies } from "next/headers";
import { getLocale } from "next-intl/server";
import { redirect } from "@/i18n/routing";
import { AdminShell } from "@/components/AdminShell";
import { TOKEN_COOKIE } from "@/lib/api";
import { decodeRole, isStaffRole } from "@/lib/auth";

export default async function AdminLayout({ children }: { children: React.ReactNode }) {
  const token = (await cookies()).get(TOKEN_COOKIE)?.value;
  const locale = await getLocale();
  if (!token) {
    redirect({ href: "/login", locale });
  }
  // Staff-only. Factory users have no place in the concierge console; send them
  // back to their own dashboard. (The API also enforces staff-only on every
  // /admin call — this is just so the UI never renders for the wrong role.)
  if (!isStaffRole(decodeRole(token!))) {
    redirect({ href: "/dashboard", locale });
  }
  return <AdminShell>{children}</AdminShell>;
}

import { cookies } from "next/headers";
import { redirect } from "@/i18n/routing";
import { getLocale } from "next-intl/server";
import { AppShell } from "@/components/AppShell";
import { TOKEN_COOKIE } from "@/lib/api";
import { decodeRole, isStaffRole } from "@/lib/auth";

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const token = (await cookies()).get(TOKEN_COOKIE)?.value;
  const locale = await getLocale();
  if (!token) {
    redirect({ href: "/login", locale });
  }
  // Staff (factory_id NULL) have no tenant to scope to — the factory pages 400
  // for them. Send them to the dedicated admin console instead of rendering
  // blank tenant screens.
  if (isStaffRole(decodeRole(token!))) {
    redirect({ href: "/admin", locale });
  }
  return <AppShell>{children}</AppShell>;
}

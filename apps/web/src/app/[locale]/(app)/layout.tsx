import { cookies } from "next/headers";
import { redirect } from "@/i18n/routing";
import { getLocale } from "next-intl/server";
import { AppShell } from "@/components/AppShell";
import { TOKEN_COOKIE } from "@/lib/api";

interface JwtPayload {
  role?: string;
}

function decodeRole(token: string): string | null {
  try {
    const payload = token.split(".")[1];
    const json = JSON.parse(Buffer.from(payload, "base64").toString("utf-8")) as JwtPayload;
    return payload ? (json.role ?? null) : null;
  } catch {
    return null;
  }
}

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const token = (await cookies()).get(TOKEN_COOKIE)?.value;
  const locale = await getLocale();
  if (!token) {
    redirect({ href: "/login", locale });
  }
  const role = token ? decodeRole(token) : null;
  return <AppShell isAdmin={role === "admin" || role === "analyst"}>{children}</AppShell>;
}

"use client";

import { useTranslations } from "next-intl";
import { Link, usePathname, useRouter } from "@/i18n/routing";
import { LocaleSwitcher } from "./LocaleSwitcher";
import { TOKEN_COOKIE } from "@/lib/api";

// The staff console is a separate shell from the factory app: internal team
// members (factory_id NULL) never see the tenant nav, and vice-versa.
const NAV = [
  // Overview lives at /admin itself, so match it exactly — otherwise it would
  // stay highlighted on every /admin/* sub-page.
  { href: "/admin", key: "overview", exact: true },
  { href: "/admin/factories", key: "factories", exact: false },
  { href: "/admin/users", key: "users", exact: false },
  { href: "/admin/campaigns", key: "campaigns", exact: false },
  { href: "/admin/suppression", key: "suppression", exact: false },
  { href: "/admin/audit", key: "audit", exact: false },
] as const;

export function AdminShell({ children }: { children: React.ReactNode }) {
  const t = useTranslations("admin");
  const app = useTranslations("app");
  const pathname = usePathname();
  const router = useRouter();

  function logout() {
    document.cookie = `${TOKEN_COOKIE}=; path=/; max-age=0`;
    router.push("/login");
    router.refresh();
  }

  return (
    <div className="min-h-screen">
      <header className="border-b border-black/5 bg-white">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
          <Link href="/admin" className="flex items-center gap-2 text-lg font-bold text-brand-700">
            {app("name")}
            <span className="rounded bg-brand-50 px-1.5 py-0.5 text-xs font-medium text-brand-700">
              {t("badge")}
            </span>
          </Link>
          <div className="flex items-center gap-3">
            <LocaleSwitcher />
            <button onClick={logout} className="text-sm text-gray-500 hover:text-gray-800">
              {t("logout")}
            </button>
          </div>
        </div>
      </header>

      <div className="mx-auto flex max-w-6xl gap-6 px-4 py-6">
        <nav className="hidden w-48 shrink-0 md:block">
          <ul className="space-y-1">
            {NAV.map((item) => {
              const active = item.exact
                ? pathname === item.href
                : pathname.startsWith(item.href);
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    className={`block rounded-lg px-3 py-2 text-sm ${
                      active
                        ? "bg-brand-50 font-medium text-brand-700"
                        : "text-gray-600 hover:bg-gray-50"
                    }`}
                  >
                    {t(item.key)}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
        <main className="min-w-0 flex-1">{children}</main>
      </div>
    </div>
  );
}

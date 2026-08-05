"use client";

import { useTranslations } from "next-intl";
import { Link, usePathname, useRouter } from "@/i18n/routing";
import { LocaleSwitcher } from "./LocaleSwitcher";

const NAV = [
  { href: "/dashboard", key: "dashboard" },
  { href: "/products", key: "products" },
  { href: "/campaigns", key: "campaigns" },
] as const;

// Account + sending configuration, grouped under a "Settings" heading in the nav.
const SETTINGS_NAV = [
  { href: "/settings/profile", key: "profile" },
  { href: "/settings/sending-email", key: "sendingEmail" },
  { href: "/settings/deliverability", key: "deliverability" },
] as const;

export function AppShell({ children }: { children: React.ReactNode }) {
  const t = useTranslations("nav");
  const app = useTranslations("app");
  const pathname = usePathname();
  const router = useRouter();

  async function logout() {
    await fetch("/api/session/logout", { method: "POST" });
    router.push("/login");
    router.refresh();
  }

  return (
    <div className="min-h-screen">
      <header className="border-b border-black/5 bg-white">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
          <Link href="/dashboard" className="text-lg font-bold text-brand-700">
            {app("name")}
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
              const active = pathname.startsWith(item.href);
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
            <li className="pt-4">
              <p className="px-3 pb-1 text-xs font-semibold uppercase tracking-wide text-gray-400">
                {t("settings")}
              </p>
              <ul className="space-y-1">
                {SETTINGS_NAV.map((item) => {
                  const active = pathname.startsWith(item.href);
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
            </li>
          </ul>
        </nav>
        <main className="min-w-0 flex-1">{children}</main>
      </div>
    </div>
  );
}

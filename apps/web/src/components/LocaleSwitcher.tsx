"use client";

import { useLocale, useTranslations } from "next-intl";
import { usePathname, useRouter } from "@/i18n/routing";

export function LocaleSwitcher() {
  const t = useTranslations("common");
  const locale = useLocale();
  const pathname = usePathname();
  const router = useRouter();

  function toggle() {
    const next = locale === "ar" ? "en" : "ar";
    router.replace(pathname, { locale: next });
  }

  return (
    <button
      onClick={toggle}
      className="rounded-lg border border-gray-200 px-2.5 py-1 text-sm text-gray-600 hover:bg-gray-50"
    >
      {t("language")}
    </button>
  );
}

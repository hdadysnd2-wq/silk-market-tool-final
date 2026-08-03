import { defineRouting } from "next-intl/routing";
import { createNavigation } from "next-intl/navigation";

export const routing = defineRouting({
  locales: ["ar", "en"],
  // Arabic is the primary locale for this Saudi-manufacturer product.
  defaultLocale: "ar",
});

export type Locale = (typeof routing.locales)[number];

export const { Link, redirect, usePathname, useRouter, getPathname } =
  createNavigation(routing);

export function dirFor(locale: string): "rtl" | "ltr" {
  return locale === "ar" ? "rtl" : "ltr";
}

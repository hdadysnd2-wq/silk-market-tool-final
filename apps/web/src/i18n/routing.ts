import { defineRouting } from "next-intl/routing";
import { createNavigation } from "next-intl/navigation";

export const routing = defineRouting({
  locales: ["ar", "en"],
  // Arabic is the primary locale for this Saudi-manufacturer product (I10 —
  // Arabic RTL-first). Browser Accept-Language detection is off on purpose:
  // most Saudi factory users run English-locale browsers/OSes, and landing
  // them on the English UI reads as broken. First visit is always Arabic; the
  // header switcher (persisted by next-intl's locale cookie) still lets anyone
  // choose English.
  defaultLocale: "ar",
  localeDetection: false,
});

export type Locale = (typeof routing.locales)[number];

export const { Link, redirect, usePathname, useRouter, getPathname } =
  createNavigation(routing);

export function dirFor(locale: string): "rtl" | "ltr" {
  return locale === "ar" ? "rtl" : "ltr";
}

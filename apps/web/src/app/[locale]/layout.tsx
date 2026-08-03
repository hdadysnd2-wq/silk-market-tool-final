import { NextIntlClientProvider } from "next-intl";
import { getMessages } from "next-intl/server";
import { notFound } from "next/navigation";
import { Inter, IBM_Plex_Sans_Arabic } from "next/font/google";
import { routing, dirFor } from "@/i18n/routing";

const latin = Inter({ subsets: ["latin"], variable: "--font-latin" });
const arabic = IBM_Plex_Sans_Arabic({
  subsets: ["arabic"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-arabic",
});

export function generateStaticParams() {
  return routing.locales.map((locale) => ({ locale }));
}

export default async function LocaleLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  if (!routing.locales.includes(locale as (typeof routing.locales)[number])) {
    notFound();
  }

  // Messages must be handed to the client provider explicitly; without this the
  // provider has no messages and every `t(...)` renders the raw key (e.g.
  // "auth.loginError") instead of the translated text.
  const messages = await getMessages();

  return (
    <html lang={locale} dir={dirFor(locale)} className={`${latin.variable} ${arabic.variable}`}>
      <body className="font-sans antialiased">
        <NextIntlClientProvider locale={locale} messages={messages}>
          {children}
        </NextIntlClientProvider>
      </body>
    </html>
  );
}

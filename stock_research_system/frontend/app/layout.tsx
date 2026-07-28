import { Rubik } from "next/font/google";
import { cookies } from "next/headers";
import type { Metadata } from "next";

import { AppProviders } from "@/providers/AppProviders";
import { DEFAULT_LOCALE, getDirection, isSupportedLocale, LOCALE_COOKIE_NAME } from "@/lib/i18n/config";

import "./globals.css";

const rubik = Rubik({ subsets: ["latin", "hebrew"], variable: "--font-rubik", display: "swap" });

export const metadata: Metadata = {
  title: "FinQuest",
  description: "FinQuest: an adaptive financial-education platform.",
};

/**
 * The locale cookie is read here, server-side, so `<html lang dir>`
 * is correct on the very first byte the browser paints - no
 * client-side flash from ltr to rtl. `LocaleProvider` (inside
 * `AppProviders`) hydrates from this same value and takes over for
 * every subsequent switch.
 */
export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const cookieStore = await cookies();
  const cookieLocale = cookieStore.get(LOCALE_COOKIE_NAME)?.value;
  const locale = isSupportedLocale(cookieLocale) ? cookieLocale : DEFAULT_LOCALE;
  const dir = getDirection(locale);

  return (
    <html lang={locale} dir={dir} className={rubik.variable}>
      <body className="font-sans">
        <AppProviders initialLocale={locale}>{children}</AppProviders>
      </body>
    </html>
  );
}

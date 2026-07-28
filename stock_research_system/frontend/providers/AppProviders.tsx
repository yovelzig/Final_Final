"use client";

import type { ReactNode } from "react";

import type { Locale } from "@/lib/i18n/config";
import { AuthProvider } from "@/providers/AuthProvider";
import { LocaleProvider } from "@/providers/LocaleProvider";
import { QueryProvider } from "@/providers/QueryProvider";

/** Root provider composition - order matters: `AuthProvider` calls
 * `useQueryClient()` to clear the cache on logout, so it must be
 * nested inside `QueryProvider`. `LocaleProvider` is outermost and
 * independent of both, since public (unauthenticated) pages still
 * need locale/translation context. */
export function AppProviders({ initialLocale, children }: { initialLocale: Locale; children: ReactNode }) {
  return (
    <LocaleProvider initialLocale={initialLocale}>
      <QueryProvider>
        <AuthProvider>{children}</AuthProvider>
      </QueryProvider>
    </LocaleProvider>
  );
}

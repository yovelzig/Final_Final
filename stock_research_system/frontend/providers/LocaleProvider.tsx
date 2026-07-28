"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { getDictionary } from "@/lib/i18n";
import { getDirection, LOCALE_COOKIE_NAME, type Direction, type Locale } from "@/lib/i18n/config";
import type { Dictionary } from "@/lib/i18n/types";

const LOCALE_COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 365;

export interface LocaleContextValue {
  locale: Locale;
  dir: Direction;
  setLocale: (locale: Locale) => void;
}

const LocaleContext = createContext<LocaleContextValue | null>(null);
const DictionaryContext = createContext<Dictionary | null>(null);

function applyDocumentLocale(locale: Locale, dir: Direction) {
  if (typeof document === "undefined") return;
  document.documentElement.lang = locale;
  document.documentElement.dir = dir;
}

function persistLocaleCookie(locale: Locale) {
  if (typeof document === "undefined") return;
  document.cookie = `${LOCALE_COOKIE_NAME}=${locale}; path=/; max-age=${LOCALE_COOKIE_MAX_AGE_SECONDS}; samesite=lax`;
}

/**
 * Client-side source of truth for the active locale. Hydrates from the
 * server-read cookie value (`initialLocale`, passed down from
 * `app/layout.tsx` so first paint already has the right `<html
 * lang dir>` - see that file for why this never causes a flash) and
 * keeps the cookie + `<html>` attributes in sync on every switch.
 * Deliberately independent of `AuthProvider`/React Query so it works
 * on public pages (landing, login) too.
 */
export function LocaleProvider({ initialLocale, children }: { initialLocale: Locale; children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(initialLocale);

  const setLocale = useCallback((next: Locale) => {
    setLocaleState(next);
    persistLocaleCookie(next);
    applyDocumentLocale(next, getDirection(next));
  }, []);

  // Keep <html> in sync even if `initialLocale` and client state ever
  // disagree (e.g. hydration from a stale cookie read).
  useEffect(() => {
    applyDocumentLocale(locale, getDirection(locale));
  }, [locale]);

  const localeValue = useMemo<LocaleContextValue>(
    () => ({ locale, dir: getDirection(locale), setLocale }),
    [locale, setLocale]
  );
  const dictionaryValue = useMemo(() => getDictionary(locale), [locale]);

  return (
    <LocaleContext.Provider value={localeValue}>
      <DictionaryContext.Provider value={dictionaryValue}>{children}</DictionaryContext.Provider>
    </LocaleContext.Provider>
  );
}

export function useLocale(): LocaleContextValue {
  const context = useContext(LocaleContext);
  if (!context) {
    throw new Error("useLocale must be used within a LocaleProvider.");
  }
  return context;
}

/** Returns the full translation dictionary for the active locale.
 * Components read strings directly off the returned object (e.g.
 * `t.dashboard.progress.title`) - there is no dynamic `t("a.b.c")`
 * lookup, so a typo or missing key is a TypeScript error, not a
 * silent runtime fallback. */
export function useDictionary(): Dictionary {
  const context = useContext(DictionaryContext);
  if (!context) {
    throw new Error("useDictionary must be used within a LocaleProvider.");
  }
  return context;
}

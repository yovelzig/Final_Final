import { en } from "@/lib/i18n/dictionaries/en";
import { he } from "@/lib/i18n/dictionaries/he";
import type { Locale } from "@/lib/i18n/config";
import type { Dictionary } from "@/lib/i18n/types";

const DICTIONARIES: Record<Locale, Dictionary> = { en, he };

/** Server- and client-safe: pure lookup, no hooks. Use this from
 * anywhere a `Locale` is already known but React context isn't
 * available (e.g. `generateMetadata`). Client components should
 * prefer `useDictionary()` from `LocaleProvider`. */
export function getDictionary(locale: Locale): Dictionary {
  return DICTIONARIES[locale];
}

/** Fills `{token}` placeholders in a translated string, e.g.
 * `interpolate(t.dashboard.welcomeBack, { name: "Ada" })`. Never used
 * for pluralization logic - pick the right key (see
 * `dashboard.progress.misconceptionsOne` vs `...Other`) before
 * interpolating. */
export function interpolate(template: string, values: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (match, token: string) => {
    const value = values[token];
    return value === undefined ? match : String(value);
  });
}

export type { Dictionary } from "@/lib/i18n/types";
export { DEFAULT_LOCALE, getDirection, isSupportedLocale, LOCALE_COOKIE_NAME, SUPPORTED_LOCALES, toIntlLocale, detectTextDirection } from "@/lib/i18n/config";
export type { Direction, Locale } from "@/lib/i18n/config";

export const SUPPORTED_LOCALES = ["en", "he"] as const;

export type Locale = (typeof SUPPORTED_LOCALES)[number];

export type Direction = "ltr" | "rtl";

export const DEFAULT_LOCALE: Locale = "en";

export const LOCALE_COOKIE_NAME = "finquest_locale";

const RTL_LOCALES: ReadonlySet<Locale> = new Set(["he"]);

export function isSupportedLocale(value: string | null | undefined): value is Locale {
  return !!value && (SUPPORTED_LOCALES as readonly string[]).includes(value);
}

export function getDirection(locale: Locale): Direction {
  return RTL_LOCALES.has(locale) ? "rtl" : "ltr";
}

/** The BCP-47 tag used for `Intl.*` formatting - distinct from the bare
 * `Locale` union, since date/number formatting needs a region. */
export function toIntlLocale(locale: Locale): string {
  return locale === "he" ? "he-IL" : "en-US";
}

/** Matches any character in the Hebrew Unicode block - used to
 * auto-detect input direction for free-text composer fields without
 * ever transforming the text itself. */
const HEBREW_CHAR_PATTERN = /[֐-׿]/;

export function detectTextDirection(value: string): Direction {
  return HEBREW_CHAR_PATTERN.test(value) ? "rtl" : "ltr";
}

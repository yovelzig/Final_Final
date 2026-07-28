"use client";

import { SUPPORTED_LOCALES, type Locale } from "@/lib/i18n/config";
import { useDictionary, useLocale } from "@/providers/LocaleProvider";
import { useAuth } from "@/hooks/useAuth";
import { useUpdateLearner } from "@/hooks/useDashboard";

const LOCALE_SHORT_LABEL: Record<Locale, string> = { en: "EN", he: "עב" };

/**
 * Persistent language toggle - always visible (landing nav, auth
 * layout, app shell). Switching updates the cookie + `<html>`
 * attributes immediately via `LocaleProvider`; when a learner is
 * signed in it also best-effort persists the choice to the real
 * `learner.preferred_language` field so it round-trips with their
 * account (never blocks or surfaces an error if that PATCH fails -
 * the cookie remains the authoritative source either way).
 */
export function LanguageSwitcher({ className = "" }: { className?: string }) {
  const { locale, setLocale } = useLocale();
  const t = useDictionary();
  const { status } = useAuth();
  const updateLearner = useUpdateLearner();

  const handleSelect = (next: Locale) => {
    if (next === locale) return;
    setLocale(next);
    if (status === "authenticated") {
      updateLearner.mutate({ preferred_language: next });
    }
  };

  return (
    <div
      role="group"
      aria-label={t.language.switcherLabel}
      className={`inline-flex items-center gap-0.5 rounded-full border border-border bg-surface p-0.5 ${className}`}
    >
      {SUPPORTED_LOCALES.map((candidate) => {
        const isActive = candidate === locale;
        return (
          <button
            key={candidate}
            type="button"
            onClick={() => handleSelect(candidate)}
            aria-pressed={isActive}
            aria-label={candidate === "en" ? t.language.english : t.language.hebrew}
            className={`rounded-full px-2.5 py-1 text-xs font-semibold transition-colors ${
              isActive ? "bg-primary text-white" : "text-slate-600 hover:bg-slate-100"
            }`}
          >
            {LOCALE_SHORT_LABEL[candidate]}
          </button>
        );
      })}
    </div>
  );
}

import { describe, expect, it } from "vitest";

import { en } from "@/lib/i18n/dictionaries/en";
import { he } from "@/lib/i18n/dictionaries/he";

/** Walks a dictionary object and returns every leaf's dotted key path.
 * Arrays are treated as leaves (their own length is what has to
 * match, not per-index parity) since `coach.suggestedPrompts` and
 * `landing.trust.points` are locale-specific prose lists, not
 * key/value maps. */
function collectLeafPaths(value: unknown, prefix = ""): string[] {
  if (Array.isArray(value) || typeof value !== "object" || value === null) {
    return [prefix];
  }
  return Object.entries(value).flatMap(([key, nested]) =>
    collectLeafPaths(nested, prefix ? `${prefix}.${key}` : key)
  );
}

describe("i18n dictionaries: en/he key parity", () => {
  it("expose exactly the same set of translation keys", () => {
    const enKeys = collectLeafPaths(en).sort();
    const heKeys = collectLeafPaths(he).sort();

    expect(heKeys).toEqual(enKeys);
  });

  it("never leaves a translated string empty", () => {
    for (const [locale, dict] of [
      ["en", en],
      ["he", he],
    ] as const) {
      for (const path of collectLeafPaths(dict)) {
        const value = path.split(".").reduce<unknown>((acc, key) => (acc as Record<string, unknown>)[key], dict);
        if (Array.isArray(value)) {
          expect(value.length, `${locale}.${path} should not be an empty array`).toBeGreaterThan(0);
          for (const item of value) {
            expect(String(item).trim().length, `${locale}.${path} item should not be blank`).toBeGreaterThan(0);
          }
        } else {
          expect(String(value).trim().length, `${locale}.${path} should not be blank`).toBeGreaterThan(0);
        }
      }
    }
  });

  it("suggestedPrompts and trust.points carry the same number of entries across locales", () => {
    expect(he.coach.suggestedPrompts).toHaveLength(en.coach.suggestedPrompts.length);
    expect(he.landing.trust.points).toHaveLength(en.landing.trust.points.length);
  });
});

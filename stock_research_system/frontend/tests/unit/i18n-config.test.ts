import { describe, expect, it } from "vitest";

import { detectTextDirection, getDirection, isSupportedLocale, toIntlLocale } from "@/lib/i18n/config";
import { interpolate } from "@/lib/i18n";

describe("getDirection", () => {
  it("is ltr for en and rtl for he", () => {
    expect(getDirection("en")).toBe("ltr");
    expect(getDirection("he")).toBe("rtl");
  });
});

describe("isSupportedLocale", () => {
  it("accepts only known locale codes", () => {
    expect(isSupportedLocale("en")).toBe(true);
    expect(isSupportedLocale("he")).toBe(true);
    expect(isSupportedLocale("fr")).toBe(false);
    expect(isSupportedLocale(null)).toBe(false);
    expect(isSupportedLocale(undefined)).toBe(false);
  });
});

describe("toIntlLocale", () => {
  it("maps to a full BCP-47 tag for Intl formatting", () => {
    expect(toIntlLocale("en")).toBe("en-US");
    expect(toIntlLocale("he")).toBe("he-IL");
  });
});

describe("detectTextDirection", () => {
  it("is ltr for plain English text", () => {
    expect(detectTextDirection("What is diversification?")).toBe("ltr");
  });

  it("is rtl for plain Hebrew text", () => {
    expect(detectTextDirection("מה זה פיזור סיכונים?")).toBe("rtl");
  });

  it("is rtl for mixed Hebrew/English/numeral text as soon as any Hebrew character is present", () => {
    expect(detectTextDirection("מה ההבדל בין ETF לבין S&P 500 ב-2024?")).toBe("rtl");
    expect(detectTextDirection("AAPL - מניה")).toBe("rtl");
  });

  it("is ltr for empty input and for numbers/tickers with no Hebrew", () => {
    expect(detectTextDirection("")).toBe("ltr");
    expect(detectTextDirection("AAPL 2024 +12.5%")).toBe("ltr");
  });
});

describe("interpolate", () => {
  it("fills a single {token} placeholder", () => {
    expect(interpolate("Welcome back, {name}", { name: "Ada" })).toBe("Welcome back, Ada");
  });

  it("fills numeric placeholders and leaves unknown tokens untouched", () => {
    expect(interpolate("{count} active misconceptions to review", { count: 3 })).toBe(
      "3 active misconceptions to review"
    );
    expect(interpolate("Hello {missing}", {})).toBe("Hello {missing}");
  });
});

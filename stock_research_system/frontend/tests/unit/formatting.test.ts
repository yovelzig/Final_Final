import { describe, expect, it } from "vitest";

import { formatCurrency, formatDate, formatDateTime, formatPercentage, formatRelativeTime, parseNumericInput } from "@/lib/formatting";

describe("formatCurrency", () => {
  it("formats a positive amount as USD by default", () => {
    expect(formatCurrency(1234.5)).toBe("$1,234.50");
  });

  it("formats a negative amount", () => {
    expect(formatCurrency(-42)).toBe("-$42.00");
  });
});

describe("formatPercentage", () => {
  it("formats a fraction as a percentage", () => {
    expect(formatPercentage(0.0523)).toBe("5.23%");
  });

  it("shows an explicit + sign when requested", () => {
    expect(formatPercentage(0.05, { signDisplay: "always" })).toBe("+5.0%");
  });
});

describe("formatDate / formatDateTime", () => {
  it("formats an ISO date string", () => {
    expect(formatDate("2026-01-15T00:00:00Z")).toContain("2026");
  });

  it("formats an ISO date-time string", () => {
    expect(formatDateTime("2026-01-15T10:30:00Z")).toContain("2026");
  });
});

describe("formatRelativeTime", () => {
  it("describes a time a few minutes in the past", () => {
    const now = new Date("2026-01-15T12:10:00Z");
    const result = formatRelativeTime("2026-01-15T12:00:00Z", now);
    expect(result).toMatch(/minute/);
  });

  it("describes a time a few days in the future", () => {
    const now = new Date("2026-01-15T12:00:00Z");
    const result = formatRelativeTime("2026-01-18T12:00:00Z", now);
    expect(result).toMatch(/day/);
  });
});

describe("parseNumericInput", () => {
  it("parses a plain integer", () => {
    expect(parseNumericInput("42")).toBe(42);
  });

  it("parses a decimal with thousands separators", () => {
    expect(parseNumericInput("1,234.56")).toBe(1234.56);
  });

  it("parses a negative number", () => {
    expect(parseNumericInput("-3.5")).toBe(-3.5);
  });

  it("returns null for empty input", () => {
    expect(parseNumericInput("")).toBeNull();
    expect(parseNumericInput("   ")).toBeNull();
  });

  it("returns null for non-numeric input", () => {
    expect(parseNumericInput("abc")).toBeNull();
    expect(parseNumericInput("1.2.3")).toBeNull();
  });
});

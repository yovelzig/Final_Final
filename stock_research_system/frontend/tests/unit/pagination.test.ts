import { describe, expect, it } from "vitest";

import { clampPageLimit, hasNextPage, nextPageOffset, type PaginatedEnvelope } from "@/lib/api/pagination";

function envelope(offset: number, returned: number, total: number): PaginatedEnvelope<unknown> {
  return { items: [], pagination: { limit: 20, offset, returned, total } };
}

describe("hasNextPage", () => {
  it("is true when more items remain after the current page", () => {
    expect(hasNextPage(envelope(0, 20, 50))).toBe(true);
  });

  it("is false on the last page", () => {
    expect(hasNextPage(envelope(40, 10, 50))).toBe(false);
  });

  it("is false for an empty result set", () => {
    expect(hasNextPage(envelope(0, 0, 0))).toBe(false);
  });
});

describe("nextPageOffset", () => {
  it("advances by the number of items actually returned", () => {
    expect(nextPageOffset(envelope(0, 20, 50))).toBe(20);
  });

  it("accounts for a short final page", () => {
    expect(nextPageOffset(envelope(40, 7, 47))).toBe(47);
  });
});

describe("clampPageLimit", () => {
  it("passes through an in-range value", () => {
    expect(clampPageLimit(50)).toBe(50);
  });

  it("clamps a value above the maximum", () => {
    expect(clampPageLimit(500)).toBe(100);
  });

  it("clamps a value at or below zero to the minimum", () => {
    expect(clampPageLimit(0)).toBe(1);
    expect(clampPageLimit(-5)).toBe(1);
  });

  it("falls back to the default for a non-finite value", () => {
    expect(clampPageLimit(Number.NaN)).toBe(20);
    expect(clampPageLimit(Number.POSITIVE_INFINITY)).toBe(20);
  });

  it("truncates a fractional value", () => {
    expect(clampPageLimit(10.9)).toBe(10);
  });
});

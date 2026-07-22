import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { buildTradeFingerprint, useIdempotencyKey } from "@/hooks/useIdempotencyKey";

describe("buildTradeFingerprint", () => {
  it("normalizes the ticker to uppercase and trims it", () => {
    const a = buildTradeFingerprint({
      portfolioId: "p1", ticker: "aapl", transactionType: "BUY", quantity: 10, requestedAt: "2026-01-01T00:00:00Z",
    });
    const b = buildTradeFingerprint({
      portfolioId: "p1", ticker: " AAPL ", transactionType: "BUY", quantity: 10, requestedAt: "2026-01-01T00:00:00Z",
    });
    expect(a).toBe(b);
  });

  it("produces a different fingerprint when the quantity changes", () => {
    const a = buildTradeFingerprint({
      portfolioId: "p1", ticker: "AAPL", transactionType: "BUY", quantity: 10, requestedAt: "2026-01-01T00:00:00Z",
    });
    const b = buildTradeFingerprint({
      portfolioId: "p1", ticker: "AAPL", transactionType: "BUY", quantity: 20, requestedAt: "2026-01-01T00:00:00Z",
    });
    expect(a).not.toBe(b);
  });
});

describe("useIdempotencyKey", () => {
  it("returns the same key across re-renders with an unchanged fingerprint", () => {
    const { result, rerender } = renderHook(({ fingerprint }) => useIdempotencyKey(fingerprint), {
      initialProps: { fingerprint: "fp-1" },
    });
    const firstKey = result.current;

    rerender({ fingerprint: "fp-1" });
    expect(result.current).toBe(firstKey);

    rerender({ fingerprint: "fp-1" });
    expect(result.current).toBe(firstKey);
  });

  it("mints a new key when the fingerprint changes (a genuinely different trade)", () => {
    const { result, rerender } = renderHook(({ fingerprint }) => useIdempotencyKey(fingerprint), {
      initialProps: { fingerprint: "fp-1" },
    });
    const firstKey = result.current;

    rerender({ fingerprint: "fp-2" });
    expect(result.current).not.toBe(firstKey);
  });
});

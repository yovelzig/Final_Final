"use client";

import { useRef } from "react";

function generateKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `idem-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

/**
 * Returns a stable `Idempotency-Key` for a trade request, keyed by a
 * caller-supplied fingerprint of the request's meaningful fields
 * (ticker/action/quantity/date/...). Retrying the exact same request
 * (same fingerprint - e.g. a network retry, or the learner clicking
 * "Confirm" again after a timeout) reuses the SAME key, so the backend
 * treats it as a replay and returns the original transaction rather
 * than executing a duplicate trade. Changing any meaningful field
 * (a different fingerprint) mints a brand new key, since that is a
 * genuinely different trade request.
 */
export function useIdempotencyKey(fingerprint: string): string {
  const lastFingerprint = useRef<string | null>(null);
  const lastKey = useRef<string | null>(null);

  if (lastFingerprint.current !== fingerprint || lastKey.current === null) {
    lastFingerprint.current = fingerprint;
    lastKey.current = generateKey();
  }

  return lastKey.current;
}

/** Builds a deterministic fingerprint string for a trade request - pure
 * function, exported separately so it (and the key-reuse behavior
 * above) can be unit-tested without rendering a component. */
export function buildTradeFingerprint(params: {
  portfolioId: string;
  ticker: string;
  transactionType: string;
  quantity: number;
  requestedAt: string;
}): string {
  return JSON.stringify([
    params.portfolioId,
    params.ticker.trim().toUpperCase(),
    params.transactionType,
    params.quantity,
    params.requestedAt,
  ]);
}

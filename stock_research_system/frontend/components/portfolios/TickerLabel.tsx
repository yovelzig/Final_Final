"use client";

import { useSecurity } from "@/hooks/usePortfolios";

/** Resolves a `security_id` (the only identifier holdings/transactions
 * responses carry) to its ticker via the learner-safe securities
 * lookup - never guesses or caches a ticker client-side. */
export function TickerLabel({ securityId }: { securityId: string }) {
  const securityQuery = useSecurity(securityId);
  if (securityQuery.isPending) {
    return <span className="inline-block h-4 w-12 animate-pulse rounded bg-slate-200" aria-hidden="true" />;
  }
  if (securityQuery.isError || !securityQuery.data) {
    return <span className="text-muted">Unknown security</span>;
  }
  return <span>{securityQuery.data.ticker}</span>;
}

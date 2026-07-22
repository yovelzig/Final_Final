import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { useExecuteTrade, usePortfolios, usePreviewTrade } from "@/hooks/usePortfolios";
import { server } from "@/tests/mocks/server";
import { renderHookWithQuery, waitFor } from "@/tests/test-utils";

const PORTFOLIO = {
  allow_fractional_shares: true, base_currency: "USD", benchmark_security_id: null, cash_balance: 9000,
  current_simulation_at: "2026-01-02T00:00:00Z", description: null, fixed_transaction_fee: 0,
  initial_cash: 10000, name: "My portfolio", portfolio_id: "portfolio-1", require_decision_journal: true,
  simulation_start_at: "2026-01-01T00:00:00Z", status: "ACTIVE", transaction_fee_bps: 0,
};

const TRANSACTION = {
  executed_at: "2026-01-02T00:00:00Z", executed_quantity: 10, execution_price: 100, fee_amount: 0,
  gross_amount: 1000, net_cash_effect: -1000, portfolio_id: "portfolio-1", rejection_message: null,
  rejection_reason: null, requested_at: "2026-01-02T00:00:00Z", requested_quantity: 10,
  security_id: "sec-1", status: "EXECUTED", transaction_id: "txn-1", transaction_type: "BUY",
};

describe("portfolio hooks (integration)", () => {
  it("lists the learner's portfolios", async () => {
    server.use(http.get("*/api/v1/portfolios", () => HttpResponse.json([PORTFOLIO])));

    const { result } = renderHookWithQuery(() => usePortfolios());
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.[0]?.name).toBe("My portfolio");
  });

  it("previews a trade without executing it (no Idempotency-Key required for preview)", async () => {
    server.use(
      http.post("*/api/v1/portfolios/portfolio-1/trades/preview", () =>
        HttpResponse.json({
          cash_after: 9000, cash_before: 10000, estimated_cash_effect: -1000, estimated_fee: 0,
          expected_execution_at: "2026-01-02T00:00:00Z", expected_execution_price: 100, gross_amount: 1000,
          quantity_after: 10, quantity_before: 0, requested_quantity: 10, ticker: "AAPL",
          transaction_type: "BUY", warnings: [],
        })
      )
    );

    const { result } = renderHookWithQuery(() => usePreviewTrade("portfolio-1"));
    result.current.mutate({ ticker: "AAPL", transaction_type: "BUY", quantity: 10, requested_at: "2026-01-02T00:00:00Z" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.expected_execution_price).toBe(100);
  });

  it("sends the caller's Idempotency-Key header on trade execution, and replaying it returns the same transaction", async () => {
    const seenKeys: string[] = [];
    server.use(
      http.post("*/api/v1/portfolios/portfolio-1/trades", ({ request }) => {
        const key = request.headers.get("Idempotency-Key");
        if (key) seenKeys.push(key);
        return HttpResponse.json(
          { transaction: TRANSACTION, portfolio: PORTFOLIO, holding: null, journal_entry: null },
          { status: 201 }
        );
      })
    );

    const { result } = renderHookWithQuery(() => useExecuteTrade("portfolio-1"));

    const body = { ticker: "AAPL", transaction_type: "BUY" as const, quantity: 10, requested_at: "2026-01-02T00:00:00Z", journal_entry: null };
    result.current.mutate({ body, idempotencyKey: "idem-key-123" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    result.current.mutate({ body, idempotencyKey: "idem-key-123" });
    await waitFor(() => expect(seenKeys.length).toBe(2));

    expect(seenKeys).toEqual(["idem-key-123", "idem-key-123"]);
    expect(result.current.data?.transaction.transaction_id).toBe("txn-1");
  });
});

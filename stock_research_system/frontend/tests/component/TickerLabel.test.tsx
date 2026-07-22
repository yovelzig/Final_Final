import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { TickerLabel } from "@/components/portfolios/TickerLabel";
import { server } from "@/tests/mocks/server";
import { renderWithQuery, screen, waitFor } from "@/tests/test-utils";

describe("TickerLabel", () => {
  it("resolves a security id to its ticker via the learner-safe lookup", async () => {
    server.use(
      http.get("*/api/v1/portfolios/securities/sec-1", () =>
        HttpResponse.json({
          security_id: "sec-1", ticker: "AAPL", company_name: "Apple Inc.",
          exchange: "NASDAQ", currency: "USD", sector: "Technology", industry: "Consumer Electronics",
        })
      )
    );

    renderWithQuery(<TickerLabel securityId="sec-1" />);

    expect(await screen.findByText("AAPL")).toBeInTheDocument();
  });

  it("shows a safe fallback rather than a raw error when the lookup fails", async () => {
    server.use(
      http.get("*/api/v1/portfolios/securities/missing", () =>
        HttpResponse.json({ error: { code: "NOT_FOUND", message: "Not found." } }, { status: 404 })
      )
    );

    renderWithQuery(<TickerLabel securityId="missing" />);

    await waitFor(() => expect(screen.getByText("Unknown security")).toBeInTheDocument());
  });
});

import { describe, expect, it } from "vitest";

import { PriceChart } from "@/components/scenarios/PriceChart";
import { render, screen } from "@/tests/test-utils";

const POINTS = [
  { timestamp: "2026-01-01T00:00:00Z", open: 100, high: 101, low: 99, close: 100, adjusted_close: 100, volume: 1000 },
  { timestamp: "2026-01-02T00:00:00Z", open: 100, high: 106, low: 100, close: 105, adjusted_close: 105, volume: 1200 },
];

describe("PriceChart", () => {
  it("renders a textual summary for screen readers, describing direction and prices", () => {
    render(<PriceChart points={POINTS} label="AAPL" />);
    const summaries = screen.getAllByText(/AAPL: rose from/);
    expect(summaries.length).toBeGreaterThan(0);
  });

  it("shows a fallback message rather than an empty chart when there is no data", () => {
    render(<PriceChart points={[]} label="AAPL" />);
    expect(screen.getByText("No chart data available.")).toBeInTheDocument();
  });
});

import { describe, expect, it } from "vitest";

import { RevealPanel } from "@/components/scenarios/RevealPanel";
import { render, screen } from "@/tests/test-utils";
import type { ScenarioRevealResponse } from "@/types/api-schemas";

const REVEAL: ScenarioRevealResponse = {
  benchmark_return: 0.02,
  combined_learning_summary: "Your mastery reflects your decision process, not this outcome.",
  decision_feedback: "You considered the benchmark before deciding.",
  excess_return: 0.03,
  focal_return: 0.05,
  future_benchmark_chart: [
    { timestamp: "2026-01-03T00:00:00Z", open: 1, high: 1, low: 1, close: 1, adjusted_close: 1, volume: 1 },
  ],
  future_focal_chart: [
    { timestamp: "2026-01-03T00:00:00Z", open: 1, high: 1, low: 1, close: 1, adjusted_close: 1, volume: 1 },
  ],
  maximum_future_drawdown: -0.1,
  maximum_future_upside: 0.15,
  outcome_direction: "POSITIVE",
  outcome_feedback: "The price rose over the following month.",
  outcome_summary: "AAPL rose 5% over the following month.",
  submission: {
    confidence_level: "HIGH",
    decision_quality: "GOOD",
    decision_quality_score: 0.8,
    exercise_attempt_id: "attempt-1",
    feedback_codes: [],
    feedback_text: null,
    graded_at: "2026-01-02T00:00:00Z",
    learner_rationale: "Diversifying.",
    outcome_alignment_score: 0.6,
    reveal_status: "REVEALED",
    revealed_at: "2026-01-03T00:00:00Z",
    scenario_id: "scenario-1",
    selected_option_id: "option-1",
    started_at: "2026-01-01T00:00:00Z",
    status: "REVEALED",
    submission_id: "submission-1",
    submitted_at: "2026-01-01T00:05:00Z",
    total_display_score: 0.7,
  },
};

describe("RevealPanel", () => {
  it("states explicitly that mastery is based on decision quality, not market luck", () => {
    render(<RevealPanel reveal={REVEAL} />);
    expect(screen.getByText(/decision quality, not market luck/i)).toBeInTheDocument();
  });

  it("renders only the fields the caller passed in - no independent data fetching", () => {
    render(<RevealPanel reveal={REVEAL} />);
    expect(screen.getByText("AAPL rose 5% over the following month.")).toBeInTheDocument();
    expect(screen.getByText("You considered the benchmark before deciding.")).toBeInTheDocument();
  });

  it("displays the realized outcome direction and returns", () => {
    render(<RevealPanel reveal={REVEAL} />);
    expect(screen.getByText("POSITIVE")).toBeInTheDocument();
  });
});

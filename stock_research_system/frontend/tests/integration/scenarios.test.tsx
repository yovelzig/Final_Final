import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { useRevealScenario, useScenario, useStartScenario, useSubmitScenarioDecision } from "@/hooks/useScenarios";
import { server } from "@/tests/mocks/server";
import { renderHookWithQuery, waitFor } from "@/tests/test-utils";

const SECURITY = {
  security_id: "sec-1", ticker: "AAPL", company_name: "Apple", exchange: "NASDAQ",
  currency: "USD", sector: null, industry: null,
};

describe("scenario hooks (integration, future-data safety)", () => {
  it("the pre-decision scenario view never includes future chart or outcome fields", async () => {
    server.use(
      http.get("*/api/v1/scenarios/scenario-1", () =>
        HttpResponse.json({
          benchmark_chart: [], benchmark_security: null, data_cutoff_at: "2026-01-01T00:00:00Z",
          decision_at: "2026-01-01T00:00:00Z", description: "d", exercise_id: "ex-1",
          exercise_options: [{ option_id: "a", option_key: "a", content: "Buy", position: 0 }],
          focal_chart: [], focal_security: SECURITY, learner_instructions: "Decide.",
          learning_objectives: [], observation_metrics: {
            annualized_volatility: null, average_daily_volume: null, benchmark_observation_return: null,
            data_cutoff_at: "2026-01-01T00:00:00Z", decision_close: 100, excess_observation_return: null,
            highest_close: 100, lowest_close: 100, maximum_drawdown: null, observation_bar_count: 1,
            observation_return: 0, price_change_percentage: 0, start_close: 100, warnings: [],
          },
          observation_start_at: "2025-12-01T00:00:00Z", prompt: "What do you do?",
          scenario_id: "scenario-1", scenario_type: "MARKET_REPLAY", scenario_version: "v1", title: "A scenario",
        })
      )
    );

    const { result } = renderHookWithQuery(() => useScenario("scenario-1"));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const data = result.current.data as unknown as Record<string, unknown>;
    expect(data).not.toHaveProperty("future_focal_chart");
    expect(data).not.toHaveProperty("outcome_direction");
    expect(data).not.toHaveProperty("focal_return");
  });

  it("only fetches reveal data when the reveal mutation is explicitly invoked", async () => {
    let revealCallCount = 0;
    server.use(
      http.post("*/api/v1/scenarios/scenario-1/start", () =>
        HttpResponse.json(
          {
            confidence_level: null, decision_quality: null, decision_quality_score: null,
            exercise_attempt_id: "attempt-1", feedback_codes: [], feedback_text: null, graded_at: null,
            learner_rationale: null, outcome_alignment_score: null, reveal_status: "HIDDEN",
            revealed_at: null, scenario_id: "scenario-1", selected_option_id: null,
            started_at: "2026-01-01T00:00:00Z", status: "STARTED", submission_id: "submission-1", submitted_at: null,
            total_display_score: null,
          },
          { status: 201 }
        )
      ),
      http.post("*/api/v1/scenarios/submissions/submission-1/submit", () =>
        HttpResponse.json({
          confidence_level: "MEDIUM", decision_quality: "GOOD", decision_quality_score: 0.7,
          exercise_attempt_id: "attempt-1", feedback_codes: [], feedback_text: null,
          graded_at: "2026-01-01T00:01:00Z", learner_rationale: "reasoning", outcome_alignment_score: null,
          reveal_status: "AVAILABLE", revealed_at: null, scenario_id: "scenario-1", selected_option_id: "a",
          started_at: "2026-01-01T00:00:00Z", status: "GRADED", submission_id: "submission-1",
          submitted_at: "2026-01-01T00:01:00Z", total_display_score: null,
        })
      ),
      http.post("*/api/v1/scenarios/submissions/submission-1/reveal", () => {
        revealCallCount += 1;
        return HttpResponse.json({
          benchmark_return: null, combined_learning_summary: "Summary.", decision_feedback: "Feedback.",
          excess_return: null, focal_return: 0.02, future_benchmark_chart: [], future_focal_chart: [],
          maximum_future_drawdown: 0, maximum_future_upside: 0.02, outcome_direction: "POSITIVE",
          outcome_feedback: "f", outcome_summary: "s",
          submission: {
            confidence_level: "MEDIUM", decision_quality: "GOOD", decision_quality_score: 0.7,
            exercise_attempt_id: "attempt-1", feedback_codes: [], feedback_text: null,
            graded_at: "2026-01-01T00:01:00Z", learner_rationale: "reasoning", outcome_alignment_score: 0.6,
            reveal_status: "REVEALED", revealed_at: "2026-01-01T00:02:00Z", scenario_id: "scenario-1",
            selected_option_id: "a", started_at: "2026-01-01T00:00:00Z", status: "REVEALED",
            submission_id: "submission-1", submitted_at: "2026-01-01T00:01:00Z", total_display_score: 0.65,
          },
        });
      })
    );

    const start = renderHookWithQuery(() => useStartScenario());
    start.result.current.mutate("scenario-1");
    await waitFor(() => expect(start.result.current.isSuccess).toBe(true));
    expect(revealCallCount).toBe(0);

    const submit = renderHookWithQuery(() => useSubmitScenarioDecision());
    submit.result.current.mutate({ submissionId: "submission-1", body: { selected_option_id: "a" } });
    await waitFor(() => expect(submit.result.current.isSuccess).toBe(true));
    expect(revealCallCount).toBe(0); // submitting a decision must never itself trigger a reveal

    const reveal = renderHookWithQuery(() => useRevealScenario());
    reveal.result.current.mutate("submission-1");
    await waitFor(() => expect(reveal.result.current.isSuccess).toBe(true));
    expect(revealCallCount).toBe(1);
    expect(reveal.result.current.data?.outcome_direction).toBe("POSITIVE");
  });
});

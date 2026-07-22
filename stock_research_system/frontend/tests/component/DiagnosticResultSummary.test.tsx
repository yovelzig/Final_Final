import { describe, expect, it } from "vitest";

import { DiagnosticResultSummary } from "@/components/adaptive/DiagnosticResultSummary";
import { render, screen } from "@/tests/test-utils";
import type { DiagnosticSummaryResponse } from "@/types/api-schemas";

const SUMMARY: DiagnosticSummaryResponse = {
  assessment: {
    assessment_id: "assessment-1",
    completed_at: "2026-01-01T00:10:00Z",
    maximum_items: 3,
    skill_ids: ["skill-1", "skill-2", "skill-3"],
    started_at: "2026-01-01T00:00:00Z",
    status: "COMPLETED",
  },
  items: [
    { assessment_id: "assessment-1", attempt_id: "a1", completed_at: "x", exercise_id: "e1", item_id: "i1", normalized_score: 1, position: 0, selected_at: "x", skill_ids: ["skill-1"] },
    { assessment_id: "assessment-1", attempt_id: "a2", completed_at: "x", exercise_id: "e2", item_id: "i2", normalized_score: 0.5, position: 1, selected_at: "x", skill_ids: ["skill-2"] },
    { assessment_id: "assessment-1", attempt_id: "a3", completed_at: null, exercise_id: "e3", item_id: "i3", normalized_score: null, position: 2, selected_at: "x", skill_ids: ["skill-3"] },
  ],
  recommended_starting_skill_ids: ["skill-3"],
  skill_results: { "skill-1": "STRONG", "skill-2": "DEVELOPING", "skill-3": "NOT_ASSESSED" },
  skill_scores: { "skill-1": 0.9, "skill-2": 0.5, "skill-3": 0 },
};

describe("DiagnosticResultSummary", () => {
  it("groups skill results by readiness level rather than showing raw skill ids", () => {
    render(<DiagnosticResultSummary summary={SUMMARY} />);

    expect(screen.getByText("Strong: 1")).toBeInTheDocument();
    expect(screen.getByText("Developing: 1")).toBeInTheDocument();
    expect(screen.getByText("Not assessed: 1")).toBeInTheDocument();
    expect(screen.queryByText("skill-1")).not.toBeInTheDocument();
  });

  it("shows how many of the assessment's questions were actually completed", () => {
    render(<DiagnosticResultSummary summary={SUMMARY} />);
    expect(screen.getByText(/You completed 2 of 3 questions\./)).toBeInTheDocument();
  });
});

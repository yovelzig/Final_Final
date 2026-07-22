import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { RecommendationCard } from "@/components/adaptive/RecommendationCard";
import { render, screen } from "@/tests/test-utils";
import type { AdaptiveDecisionResponse } from "@/types/api-schemas";

const DECISION: AdaptiveDecisionResponse = {
  accepted_at: null,
  completed_at: null,
  decision_id: "decision-1",
  explanation: "You have an active misconception about diversification.",
  generated_at: "2026-01-01T00:00:00Z",
  priority_score: 0.9,
  reason_codes: ["ACTIVE_MISCONCEPTION"],
  recommendation_type: "MISCONCEPTION_REMEDIATION",
  recommended_difficulty_score: 0.5,
  recommended_exercise_id: "exercise-1",
  recommended_lesson_id: "lesson-1",
  session_id: "session-1",
  skipped_at: null,
  status: "GENERATED",
  target_skill_ids: ["skill-1"],
};

describe("RecommendationCard", () => {
  it("translates recommendation type and reason codes into learner-friendly text", () => {
    render(
      <RecommendationCard
        decision={DECISION}
        exercise={null}
        lesson={null}
        onAccept={vi.fn()}
        onSkip={vi.fn()}
        isAccepting={false}
        isSkipping={false}
      />
    );

    expect(screen.getByText("Clear up a misconception")).toBeInTheDocument();
    expect(screen.getByText("You have an active misconception here")).toBeInTheDocument();
    expect(screen.getByText(DECISION.explanation)).toBeInTheDocument();
  });

  it("calls onAccept and onSkip from their respective buttons", async () => {
    const user = userEvent.setup();
    const onAccept = vi.fn();
    const onSkip = vi.fn();
    render(
      <RecommendationCard
        decision={DECISION}
        exercise={null}
        lesson={null}
        onAccept={onAccept}
        onSkip={onSkip}
        isAccepting={false}
        isSkipping={false}
      />
    );

    await user.click(screen.getByRole("button", { name: "Start this" }));
    expect(onAccept).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "Skip" }));
    expect(onSkip).toHaveBeenCalledTimes(1);
  });

  it("never displays a priority or difficulty score as a raw number to the learner", () => {
    render(
      <RecommendationCard
        decision={DECISION}
        exercise={null}
        lesson={null}
        onAccept={vi.fn()}
        onSkip={vi.fn()}
        isAccepting={false}
        isSkipping={false}
      />
    );
    expect(screen.queryByText("0.9")).not.toBeInTheDocument();
    expect(screen.queryByText("0.5")).not.toBeInTheDocument();
  });
});

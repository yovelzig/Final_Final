import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { useNextRecommendation, useStartSession } from "@/hooks/useAdaptive";
import { server } from "@/tests/mocks/server";
import { renderHookWithQuery, waitFor } from "@/tests/test-utils";

describe("adaptive practice hooks (integration)", () => {
  it("starts a session and requests a recommendation", async () => {
    server.use(
      http.post("*/api/v1/adaptive/sessions", async ({ request }) => {
        const body = (await request.json()) as { session_type: string };
        expect(body.session_type).toBe("DAILY_PRACTICE");
        return HttpResponse.json(
          {
            completed_at: null, completed_item_count: 0, correct_item_count: 0, goal_minutes: 10,
            last_activity_at: "2026-01-01T00:00:00Z", maximum_score: 0, recommended_item_count: 0,
            session_id: "session-1", session_type: "DAILY_PRACTICE", started_at: "2026-01-01T00:00:00Z",
            status: "STARTED", total_score: 0,
          },
          { status: 201 }
        );
      }),
      http.post("*/api/v1/adaptive/sessions/session-1/next", () =>
        HttpResponse.json({
          decision: {
            accepted_at: null, completed_at: null, decision_id: "decision-1",
            explanation: "Time to review.", generated_at: "2026-01-01T00:00:00Z", priority_score: 0.5,
            reason_codes: ["OVERDUE_REVIEW"], recommendation_type: "REVIEW_EXERCISE",
            recommended_difficulty_score: 0.5, recommended_exercise_id: "ex-1", recommended_lesson_id: "lesson-1",
            session_id: "session-1", skipped_at: null, status: "GENERATED", target_skill_ids: ["skill-1"],
          },
          exercise: {
            exercise_id: "ex-1", lesson_id: "lesson-1", exercise_type: "SINGLE_CHOICE", prompt: "Review question",
            difficulty: "BEGINNER", position: 0, skill_ids: ["skill-1"], maximum_score: 1, passing_score: 1,
            options: [{ option_id: "a", option_key: "a", content: "Answer", position: 0 }],
          },
          lesson: null,
        })
      )
    );

    const session = renderHookWithQuery(() => useStartSession());
    session.result.current.mutate({ session_type: "DAILY_PRACTICE" });
    await waitFor(() => expect(session.result.current.isSuccess).toBe(true));

    const next = renderHookWithQuery(() => useNextRecommendation());
    next.result.current.mutate("session-1");
    await waitFor(() => expect(next.result.current.isSuccess).toBe(true));

    expect(next.result.current.data?.decision.recommendation_type).toBe("REVIEW_EXERCISE");
    expect(next.result.current.data?.exercise?.prompt).toBe("Review question");
  });

  it("recognizes a SESSION_COMPLETE recommendation with no attached exercise", async () => {
    server.use(
      http.post("*/api/v1/adaptive/sessions/session-2/next", () =>
        HttpResponse.json({
          decision: {
            accepted_at: null, completed_at: null, decision_id: "decision-2",
            explanation: "You've reached your daily goal.", generated_at: "2026-01-01T00:00:00Z",
            priority_score: 1, reason_codes: ["DAILY_GOAL_REACHED"], recommendation_type: "SESSION_COMPLETE",
            recommended_difficulty_score: null, recommended_exercise_id: null, recommended_lesson_id: null,
            session_id: "session-2", skipped_at: null, status: "GENERATED", target_skill_ids: [],
          },
          exercise: null,
          lesson: null,
        })
      )
    );

    const next = renderHookWithQuery(() => useNextRecommendation());
    next.result.current.mutate("session-2");
    await waitFor(() => expect(next.result.current.isSuccess).toBe(true));

    expect(next.result.current.data?.decision.recommendation_type).toBe("SESSION_COMPLETE");
    expect(next.result.current.data?.exercise).toBeNull();
  });
});

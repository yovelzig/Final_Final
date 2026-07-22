import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { useDashboard, useMastery } from "@/hooks/useDashboard";
import { server } from "@/tests/mocks/server";
import { renderHookWithQuery, waitFor } from "@/tests/test-utils";

describe("useDashboard (integration)", () => {
  it("fetches and exposes the real backend dashboard shape, with no fabricated fields", async () => {
    server.use(
      http.get("*/api/v1/learners/me/dashboard", () =>
        HttpResponse.json({
          active_path_id: "path-1",
          active_misconceptions: [],
          completed_lessons: 3,
          current_lesson_id: null,
          current_streak_days: 0,
          learner: {
            learner_id: "learner-1", display_name: "Ada", daily_goal_minutes: 10,
            preferred_language: "en", financial_experience_level: "BEGINNER",
          },
          skill_mastery: [],
          total_lessons: 10,
          total_xp: 0,
        })
      )
    );

    const { result } = renderHookWithQuery(() => useDashboard());

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.completed_lessons).toBe(3);
    expect(result.current.data?.total_lessons).toBe(10);
  });

  it("surfaces a backend error as a typed FinQuestApiError with a correlation id", async () => {
    server.use(
      http.get("*/api/v1/learners/me/dashboard", () =>
        HttpResponse.json(
          { error: { code: "INTERNAL_ERROR", message: "Try again later.", correlation_id: "corr-9" } },
          { status: 500 }
        )
      )
    );

    const { result } = renderHookWithQuery(() => useDashboard());

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).toMatchObject({ correlationId: "corr-9", message: "Try again later." });
  });
});

describe("useMastery (integration, pagination)", () => {
  it("parses the paginated envelope's items and pagination metadata", async () => {
    server.use(
      http.get("*/api/v1/learners/me/mastery", () =>
        HttpResponse.json({
          items: [{ skill_id: "s1", mastery_score: 0.8, skill_name: "Budgeting" }],
          pagination: { limit: 50, offset: 0, returned: 1, total: 1 },
        })
      )
    );

    const { result } = renderHookWithQuery(() => useMastery());

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.items).toHaveLength(1);
    expect(result.current.data?.pagination.total).toBe(1);
  });
});

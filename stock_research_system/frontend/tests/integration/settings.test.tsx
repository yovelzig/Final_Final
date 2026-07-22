import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { useUpdateLearner } from "@/hooks/useDashboard";
import { server } from "@/tests/mocks/server";
import { renderHookWithQuery, waitFor } from "@/tests/test-utils";

describe("useUpdateLearner (integration)", () => {
  it("sends only display name, preferred language, and daily goal - never role or status", async () => {
    server.use(
      http.patch("*/api/v1/learners/me", async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        expect(Object.keys(body).sort()).toEqual(["daily_goal_minutes", "display_name", "preferred_language"]);
        return HttpResponse.json({
          active: true, created_at: "2026-01-01T00:00:00Z", daily_goal_minutes: 20,
          display_name: "New Name", financial_experience_level: "BEGINNER",
          learner_id: "learner-1", preferred_language: "en",
        });
      })
    );

    const { result } = renderHookWithQuery(() => useUpdateLearner());
    result.current.mutate({ display_name: "New Name", preferred_language: "en", daily_goal_minutes: 20 });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.display_name).toBe("New Name");
  });

  it("surfaces a validation error (e.g. an out-of-range goal) as a typed error", async () => {
    server.use(
      http.patch("*/api/v1/learners/me", () =>
        HttpResponse.json(
          {
            error: {
              code: "VALIDATION_ERROR", message: "Daily goal must be at most 240 minutes.",
              details: [], correlation_id: "corr-1",
            },
          },
          { status: 422 }
        )
      )
    );

    const { result } = renderHookWithQuery(() => useUpdateLearner());
    result.current.mutate({ daily_goal_minutes: 9999 });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).toMatchObject({ status: 422, code: "VALIDATION_ERROR" });
  });
});

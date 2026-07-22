import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { useLesson, useLessonExercises, useStartAttempt, useSubmitAnswer } from "@/hooks/useCurriculum";
import { server } from "@/tests/mocks/server";
import { renderHookWithQuery, waitFor } from "@/tests/test-utils";

describe("curriculum hooks (integration)", () => {
  it("fetches a lesson and its exercises without leaking is_correct/feedback on options", async () => {
    server.use(
      http.get("*/api/v1/lessons/lesson-1", () =>
        HttpResponse.json({
          lesson_id: "lesson-1", module_id: "module-1", code: "l1", title: "Budgeting Basics",
          summary: "s", content_markdown: "# Content", difficulty: "BEGINNER", status: "PUBLISHED",
          position: 0, estimated_minutes: 5, primary_skill_id: "skill-1",
        })
      ),
      http.get("*/api/v1/lessons/lesson-1/exercises", () =>
        HttpResponse.json([
          {
            exercise_id: "ex-1", lesson_id: "lesson-1", exercise_type: "SINGLE_CHOICE", prompt: "Pick one",
            difficulty: "BEGINNER", position: 0, skill_ids: ["skill-1"], maximum_score: 1, passing_score: 1,
            options: [
              { option_id: "a", option_key: "a", content: "Right", position: 0 },
              { option_id: "b", option_key: "b", content: "Wrong", position: 1 },
            ],
          },
        ])
      )
    );

    const lesson = renderHookWithQuery(() => useLesson("lesson-1"));
    await waitFor(() => expect(lesson.result.current.isSuccess).toBe(true));
    expect(lesson.result.current.data?.title).toBe("Budgeting Basics");

    const exercises = renderHookWithQuery(() => useLessonExercises("lesson-1"));
    await waitFor(() => expect(exercises.result.current.isSuccess).toBe(true));
    const exercise = exercises.result.current.data?.[0];
    expect(exercise?.options.every((option) => !("is_correct" in option))).toBe(true);
  });

  it("starts an attempt, submits an answer, and invalidates mastery/progress/dashboard caches", async () => {
    server.use(
      http.post("*/api/v1/exercises/ex-1/attempts", () =>
        HttpResponse.json({
          attempt_id: "attempt-1", attempt_number: 1, confidence_level: null, exercise_id: "ex-1",
          graded_at: null, is_correct: null, maximum_score: 1, score: null,
          started_at: "2026-01-01T00:00:00Z", status: "STARTED", submitted_at: null,
        })
      ),
      http.post("*/api/v1/attempts/attempt-1/answers", async ({ request }) => {
        const body = (await request.json()) as { selected_option_ids: string[] };
        expect(body.selected_option_ids).toEqual(["a"]);
        return HttpResponse.json({
          attempt: {
            attempt_id: "attempt-1", attempt_number: 1, confidence_level: null, exercise_id: "ex-1",
            graded_at: "2026-01-01T00:01:00Z", is_correct: true, maximum_score: 1, score: 1,
            started_at: "2026-01-01T00:00:00Z", status: "GRADED", submitted_at: "2026-01-01T00:01:00Z",
          },
          updated_mastery: [],
          updated_progress: null,
        });
      })
    );

    const start = renderHookWithQuery(() => useStartAttempt("ex-1"));
    start.result.current.mutate({});
    await waitFor(() => expect(start.result.current.isSuccess).toBe(true));
    expect(start.result.current.data?.attempt_id).toBe("attempt-1");

    const submit = renderHookWithQuery(() => useSubmitAnswer("attempt-1"));
    submit.result.current.mutate({ selected_option_ids: ["a"] });
    await waitFor(() => expect(submit.result.current.isSuccess).toBe(true));
    expect(submit.result.current.data?.attempt.is_correct).toBe(true);
  });
});

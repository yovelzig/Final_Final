import { delay, http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { LessonPageContent } from "@/app/(protected)/lessons/[lessonId]/LessonPageContent";
import { queryKeys } from "@/lib/api/query-keys";
import { server } from "@/tests/mocks/server";
import { renderWithQuery, screen, waitFor } from "@/tests/test-utils";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

const LESSON_ID = "lesson-1";
const EXERCISE_PROMPT = "Which of the following is NOT one of the three basic functions of money?";

function createDeferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

function mockLesson() {
  server.use(
    http.get(`*/api/v1/lessons/${LESSON_ID}`, () =>
      HttpResponse.json({
        lesson_id: LESSON_ID,
        module_id: "module-1",
        code: "l1",
        title: "What Money Is For",
        summary: "s",
        content_markdown: "# Content",
        difficulty: "BEGINNER",
        status: "PUBLISHED",
        position: 0,
        estimated_minutes: 5,
        primary_skill_id: "skill-1",
      })
    ),
    // A single minimal, learner-safe exercise - no is_correct, option
    // feedback, explanation, or grading configuration - so the
    // safety-gate tests can prove the exercise UI itself (not just the
    // lesson content) survives while completion data is unavailable.
    http.get(`*/api/v1/lessons/${LESSON_ID}/exercises`, () =>
      HttpResponse.json([
        {
          exercise_id: "ex-1",
          lesson_id: LESSON_ID,
          exercise_type: "SINGLE_CHOICE",
          prompt: EXERCISE_PROMPT,
          difficulty: "BEGINNER",
          position: 0,
          skill_ids: ["skill-1"],
          maximum_score: 1,
          passing_score: 1,
          options: [
            { option_id: "a", option_key: "a", content: "A medium of exchange", position: 0 },
            { option_id: "b", option_key: "b", content: "A guarantee of investment profit", position: 1 },
          ],
        },
      ])
    )
  );
}

function dashboardBody(currentLessonId: string | null) {
  return {
    active_path_id: "path-1",
    current_lesson_id: currentLessonId,
    completed_lessons: 1,
    total_lessons: 5,
    current_streak_days: 1,
    total_xp: 10,
    learner: {
      learner_id: "l1",
      display_name: "Ada",
      daily_goal_minutes: 10,
      preferred_language: "en",
      financial_experience_level: "BEGINNER",
    },
    skill_mastery: [],
    active_misconceptions: [],
  };
}

function mockDashboard(currentLessonId: string | null) {
  server.use(http.get("*/api/v1/learners/me/dashboard", () => HttpResponse.json(dashboardBody(currentLessonId))));
}

function progressBody(items: Array<{ lessonId: string; status: string }>) {
  return {
    items: items.map(({ lessonId, status }) => ({
      progress_id: `progress-${lessonId}`,
      path_id: "path-1",
      module_id: "module-1",
      lesson_id: lessonId,
      status,
      completion_percentage: status === "NOT_STARTED" ? 0 : 1,
      best_score: null,
      attempt_count: 1,
      completed_at: status === "NOT_STARTED" ? null : "2026-01-01T00:00:00Z",
    })),
    pagination: { limit: 50, offset: 0, returned: items.length, total: items.length },
  };
}

function mockProgress(items: Array<{ lessonId: string; status: string }>) {
  server.use(http.get("*/api/v1/learners/me/progress", () => HttpResponse.json(progressBody(items))));
}

function renderLessonPage() {
  return renderWithQuery(<LessonPageContent lessonId={LESSON_ID} />);
}

describe("LessonPage completion UI", () => {
  it("Case A: renders no completion banner when the lesson is not terminal", async () => {
    mockLesson();
    mockDashboard(LESSON_ID);
    mockProgress([{ lessonId: LESSON_ID, status: "IN_PROGRESS" }]);

    renderLessonPage();
    await screen.findByText("What Money Is For");
    await waitFor(() => expect(screen.queryByText("Lesson complete.")).not.toBeInTheDocument());
    expect(screen.queryByText(/all caught up/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Continue learning" })).not.toBeInTheDocument();
  });

  it("Case A: renders no completion banner when there is no progress row for this lesson", async () => {
    mockLesson();
    mockDashboard(null);
    mockProgress([]);

    renderLessonPage();
    await screen.findByText("What Money Is For");
    await waitFor(() => expect(screen.queryByText("Lesson complete.")).not.toBeInTheDocument());
  });

  it("Case B: COMPLETED status with a different current lesson shows Continue learning", async () => {
    mockLesson();
    mockDashboard("lesson-2");
    mockProgress([{ lessonId: LESSON_ID, status: "COMPLETED" }]);

    renderLessonPage();
    await screen.findByText("Lesson complete.");
    const link = await screen.findByRole("link", { name: "Continue learning" });
    expect(link).toHaveAttribute("href", "/lessons/lesson-2");
    // Native anchor, not next/link's client-side transition - see
    // LessonPageContent.tsx for why this CTA intentionally performs a
    // full document navigation.
    expect(link.tagName).toBe("A");
  });

  it("Case B: MASTERED status with a different current lesson shows Continue learning", async () => {
    mockLesson();
    mockDashboard("lesson-2");
    mockProgress([{ lessonId: LESSON_ID, status: "MASTERED" }]);

    renderLessonPage();
    await screen.findByText("Lesson complete.");
    const link = await screen.findByRole("link", { name: "Continue learning" });
    expect(link).toHaveAttribute("href", "/lessons/lesson-2");
    expect(link.tagName).toBe("A");
  });

  it("Case C: null current_lesson_id shows the all-caught-up wording linking to /learn", async () => {
    mockLesson();
    mockDashboard(null);
    mockProgress([{ lessonId: LESSON_ID, status: "COMPLETED" }]);

    renderLessonPage();
    await screen.findByText("You're all caught up.");
    await screen.findByText("Review the available learning paths to continue.");
    const link = await screen.findByRole("link", { name: "Review learning paths" });
    expect(link).toHaveAttribute("href", "/learn");
  });

  it("Case D: a stale self-reference never self-links and never uses the all-caught-up wording", async () => {
    mockLesson();
    mockDashboard(LESSON_ID);
    mockProgress([{ lessonId: LESSON_ID, status: "COMPLETED" }]);

    renderLessonPage();
    await screen.findByText("Lesson complete.");
    expect(screen.queryByText("You're all caught up.")).not.toBeInTheDocument();

    const link = await screen.findByRole("link", { name: "Review learning paths" });
    expect(link).toHaveAttribute("href", "/learn");

    const allLinks = screen.getAllByRole("link");
    expect(allLinks.every((anchor) => anchor.getAttribute("href") !== `/lessons/${LESSON_ID}`)).toBe(true);
  });

  it.each([
    {
      label: "dashboard pending (never resolves)",
      setup: () =>
        server.use(
          http.get("*/api/v1/learners/me/dashboard", async () => {
            await delay("infinite");
          }),
          http.get("*/api/v1/learners/me/progress", () =>
            HttpResponse.json(progressBody([{ lessonId: LESSON_ID, status: "COMPLETED" }]))
          )
        ),
    },
    {
      label: "dashboard error",
      setup: () =>
        server.use(
          http.get("*/api/v1/learners/me/dashboard", () =>
            HttpResponse.json({ error: { code: "SERVER_ERROR", message: "boom" } }, { status: 500 })
          ),
          http.get("*/api/v1/learners/me/progress", () =>
            HttpResponse.json(progressBody([{ lessonId: LESSON_ID, status: "COMPLETED" }]))
          )
        ),
    },
    {
      label: "progress pending (never resolves)",
      setup: () =>
        server.use(
          http.get("*/api/v1/learners/me/dashboard", () => HttpResponse.json(dashboardBody("lesson-2"))),
          http.get("*/api/v1/learners/me/progress", async () => {
            await delay("infinite");
          })
        ),
    },
    {
      label: "progress error",
      setup: () =>
        server.use(
          http.get("*/api/v1/learners/me/dashboard", () => HttpResponse.json(dashboardBody("lesson-2"))),
          http.get("*/api/v1/learners/me/progress", () =>
            HttpResponse.json({ error: { code: "SERVER_ERROR", message: "boom" } }, { status: 500 })
          )
        ),
    },
  ])("safety gate: keeps lesson content and exercises visible with no completion banner when $label", async ({ setup }) => {
    mockLesson();
    setup();

    renderLessonPage();
    await screen.findByText("What Money Is For");
    expect(screen.getByText(EXERCISE_PROMPT)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start exercise" })).toBeInTheDocument();
    expect(screen.queryByText("Lesson complete.")).not.toBeInTheDocument();
    expect(screen.queryByText(/all caught up/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Continue learning" })).not.toBeInTheDocument();
  });

  it.each([
    {
      label: "dashboard",
      queryKey: queryKeys.learner.dashboard(),
      overrideHandler: (deferred: ReturnType<typeof createDeferred<void>>) =>
        http.get("*/api/v1/learners/me/dashboard", async () => {
          await deferred.promise;
          return HttpResponse.json(dashboardBody("lesson-2"));
        }),
    },
    {
      label: "progress",
      queryKey: queryKeys.learner.progress(),
      overrideHandler: (deferred: ReturnType<typeof createDeferred<void>>) =>
        http.get("*/api/v1/learners/me/progress", async () => {
          await deferred.promise;
          return HttpResponse.json(progressBody([{ lessonId: LESSON_ID, status: "COMPLETED" }]));
        }),
    },
  ])(
    "safety gate: hides the completion banner while the $label query refetches after a prior success, and keeps lesson content and exercises visible",
    async ({ queryKey, overrideHandler }) => {
      mockLesson();
      mockDashboard("lesson-2");
      mockProgress([{ lessonId: LESSON_ID, status: "COMPLETED" }]);

      const { queryClient } = renderLessonPage();
      await screen.findByRole("link", { name: "Continue learning" });

      const deferred = createDeferred<void>();
      server.use(overrideHandler(deferred));

      void queryClient.invalidateQueries({ queryKey });

      await waitFor(() => expect(screen.queryByRole("link", { name: "Continue learning" })).not.toBeInTheDocument());
      expect(screen.getByText("What Money Is For")).toBeInTheDocument();
      expect(screen.getByText(EXERCISE_PROMPT)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Start exercise" })).toBeInTheDocument();

      deferred.resolve();
      await screen.findByRole("link", { name: "Continue learning" });
    }
  );
});

import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { ExercisePlayer } from "@/components/exercises/ExercisePlayer";
import { server } from "@/tests/mocks/server";
import { renderWithQuery, screen, waitFor } from "@/tests/test-utils";
import type { ExerciseResponse } from "@/types/api-schemas";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

const EXERCISE: ExerciseResponse = {
  exercise_id: "ex-1",
  lesson_id: "lesson-1",
  exercise_type: "SINGLE_CHOICE",
  prompt: "Pick the right one",
  difficulty: "BEGINNER",
  position: 0,
  skill_ids: ["skill-1"],
  maximum_score: 1,
  passing_score: 1,
  options: [
    { option_id: "a", option_key: "a", content: "Right answer", position: 0 },
    { option_id: "b", option_key: "b", content: "Wrong answer", position: 1 },
  ],
};

function mockStartAttempt() {
  server.use(
    http.post("*/api/v1/exercises/ex-1/attempts", () =>
      HttpResponse.json({
        attempt_id: "attempt-1",
        attempt_number: 1,
        confidence_level: null,
        exercise_id: "ex-1",
        graded_at: null,
        is_correct: null,
        maximum_score: 1,
        score: null,
        started_at: "2026-01-01T00:00:00Z",
        status: "STARTED",
        submitted_at: null,
      })
    )
  );
}

function mockSubmitAnswer(explanation: string | null) {
  server.use(
    http.post("*/api/v1/attempts/attempt-1/answers", () =>
      HttpResponse.json({
        attempt: {
          attempt_id: "attempt-1",
          attempt_number: 1,
          confidence_level: null,
          exercise_id: "ex-1",
          graded_at: "2026-01-01T00:01:00Z",
          is_correct: true,
          maximum_score: 1,
          score: 1,
          started_at: "2026-01-01T00:00:00Z",
          status: "GRADED",
          submitted_at: "2026-01-01T00:01:00Z",
        },
        updated_mastery: [],
        updated_progress: null,
        explanation,
      })
    )
  );
}

function mockSubmitAnswerWithProgress(completionPercentage: number) {
  server.use(
    http.post("*/api/v1/attempts/attempt-1/answers", () =>
      HttpResponse.json({
        attempt: {
          attempt_id: "attempt-1",
          attempt_number: 1,
          confidence_level: null,
          exercise_id: "ex-1",
          graded_at: "2026-01-01T00:01:00Z",
          is_correct: true,
          maximum_score: 1,
          score: 1,
          started_at: "2026-01-01T00:00:00Z",
          status: "GRADED",
          submitted_at: "2026-01-01T00:01:00Z",
        },
        updated_mastery: [],
        updated_progress: {
          progress_id: "progress-1",
          path_id: "path-1",
          module_id: "module-1",
          lesson_id: "lesson-1",
          status: completionPercentage >= 100 ? "COMPLETED" : "IN_PROGRESS",
          completion_percentage: completionPercentage,
          best_score: 1,
          attempt_count: 1,
          completed_at: null,
        },
        explanation: null,
      })
    )
  );
}

async function startAndAnswer(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "Start exercise" }));
  await waitFor(() => expect(screen.getByRole("radio", { name: "Right answer" })).toBeInTheDocument());
  await user.click(screen.getByRole("radio", { name: "Right answer" }));
  await user.click(screen.getByRole("button", { name: "Submit answer" }));
}

describe("ExercisePlayer retry and explanation rendering", () => {
  it("shows no explanation before submission, renders it after a graded answer, and clears it on retry", async () => {
    const user = userEvent.setup();
    mockStartAttempt();
    mockSubmitAnswer("Money's three functions are exchange, store of value, and unit of account.");

    renderWithQuery(<ExercisePlayer exercise={EXERCISE} />);

    expect(screen.queryByTestId("exercise-explanation")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Start exercise" }));
    await waitFor(() => expect(screen.getByRole("radio", { name: "Right answer" })).toBeInTheDocument());
    expect(screen.queryByTestId("exercise-explanation")).not.toBeInTheDocument();

    await user.click(screen.getByRole("radio", { name: "Right answer" }));
    await user.click(screen.getByRole("button", { name: "Submit answer" }));

    await waitFor(() =>
      expect(screen.getByTestId("exercise-explanation")).toHaveTextContent(
        "Money's three functions are exchange, store of value, and unit of account."
      )
    );
    expect(screen.getByText("Correct")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Try another attempt" }));

    expect(screen.queryByTestId("exercise-explanation")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start exercise" })).toBeInTheDocument();
  });

  it("renders no explanation container for a null explanation", async () => {
    const user = userEvent.setup();
    mockStartAttempt();
    mockSubmitAnswer(null);

    renderWithQuery(<ExercisePlayer exercise={EXERCISE} />);
    await startAndAnswer(user);

    await waitFor(() => expect(screen.getByText("Correct")).toBeInTheDocument());
    expect(screen.queryByTestId("exercise-explanation")).not.toBeInTheDocument();
  });
});

describe("ExerciseResult lesson-progress percentage rendering", () => {
  it("renders a partial completion_percentage (already 0-100) without double-scaling it", async () => {
    const user = userEvent.setup();
    mockStartAttempt();
    mockSubmitAnswerWithProgress(33.3333333333);

    renderWithQuery(<ExercisePlayer exercise={EXERCISE} />);
    await startAndAnswer(user);

    await waitFor(() => expect(screen.getByText("Lesson progress: 33% complete.")).toBeInTheDocument());
    expect(screen.queryByText(/3333%/)).not.toBeInTheDocument();
  });

  it("renders a completed completion_percentage of 100 without double-scaling it", async () => {
    const user = userEvent.setup();
    mockStartAttempt();
    mockSubmitAnswerWithProgress(100);

    renderWithQuery(<ExercisePlayer exercise={EXERCISE} />);
    await startAndAnswer(user);

    await waitFor(() => expect(screen.getByText("Lesson progress: 100% complete.")).toBeInTheDocument());
    expect(screen.queryByText(/10000%/)).not.toBeInTheDocument();
  });
});

describe("SingleSelectInput independent radio groups across mounted exercises", () => {
  const SINGLE_CHOICE_EXERCISE: ExerciseResponse = {
    exercise_id: "ex-single",
    lesson_id: "lesson-1",
    exercise_type: "SINGLE_CHOICE",
    prompt: "Pick the right one",
    difficulty: "BEGINNER",
    position: 0,
    skill_ids: ["skill-1"],
    maximum_score: 1,
    passing_score: 1,
    options: [
      { option_id: "right", option_key: "a", content: "Right answer", position: 0 },
      { option_id: "wrong", option_key: "b", content: "Wrong answer", position: 1 },
    ],
  };

  const TRUE_FALSE_EXERCISE: ExerciseResponse = {
    exercise_id: "ex-true-false",
    lesson_id: "lesson-1",
    exercise_type: "TRUE_FALSE",
    prompt: "True or false question",
    difficulty: "BEGINNER",
    position: 1,
    skill_ids: ["skill-1"],
    maximum_score: 1,
    passing_score: 1,
    options: [
      { option_id: "true-option", option_key: "true", content: "True", position: 0 },
      { option_id: "false-option", option_key: "false", content: "False", position: 1 },
    ],
  };

  function mockStartAttemptFor(exerciseId: string, attemptId: string) {
    server.use(
      http.post(`*/api/v1/exercises/${exerciseId}/attempts`, () =>
        HttpResponse.json({
          attempt_id: attemptId,
          attempt_number: 1,
          confidence_level: null,
          exercise_id: exerciseId,
          graded_at: null,
          is_correct: null,
          maximum_score: 1,
          score: null,
          started_at: "2026-01-01T00:00:00Z",
          status: "STARTED",
          submitted_at: null,
        })
      )
    );
  }

  it("keeps two mounted exercises' selections independent and gives their radio groups different names", async () => {
    const user = userEvent.setup();
    mockStartAttemptFor("ex-single", "attempt-single");
    mockStartAttemptFor("ex-true-false", "attempt-true-false");

    renderWithQuery(
      <>
        <ExercisePlayer exercise={SINGLE_CHOICE_EXERCISE} />
        <ExercisePlayer exercise={TRUE_FALSE_EXERCISE} />
      </>
    );

    const [firstStartButton, secondStartButton] = screen.getAllByRole("button", { name: "Start exercise" });
    expect(firstStartButton).toBeInTheDocument();
    expect(secondStartButton).toBeInTheDocument();
    await user.click(firstStartButton!);
    await user.click(secondStartButton!);

    await waitFor(() => expect(screen.getByRole("radio", { name: "Right answer" })).toBeInTheDocument());
    await waitFor(() => expect(screen.getByRole("radio", { name: "True" })).toBeInTheDocument());

    const rightAnswerRadio = screen.getByRole("radio", { name: "Right answer" });
    const wrongAnswerRadio = screen.getByRole("radio", { name: "Wrong answer" });
    const trueRadio = screen.getByRole("radio", { name: "True" });
    const falseRadio = screen.getByRole("radio", { name: "False" });

    await user.click(rightAnswerRadio);
    expect(rightAnswerRadio).toBeChecked();

    await user.click(trueRadio);
    expect(trueRadio).toBeChecked();

    // The regression this guards against: selecting an option in the second
    // exercise must never clear the first exercise's selection because they
    // shared one browser-level radio group name.
    expect(rightAnswerRadio).toBeChecked();

    expect(rightAnswerRadio.getAttribute("name")).toBe(wrongAnswerRadio.getAttribute("name"));
    expect(trueRadio.getAttribute("name")).toBe(falseRadio.getAttribute("name"));
    expect(rightAnswerRadio.getAttribute("name")).not.toBe(trueRadio.getAttribute("name"));
  });
});

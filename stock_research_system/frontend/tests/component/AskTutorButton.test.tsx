import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { AskTutorButton } from "@/components/tutor/AskTutorButton";
import { server } from "@/tests/mocks/server";
import { renderWithQuery, screen, waitFor } from "@/tests/test-utils";

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

describe("AskTutorButton", () => {
  it("creates a context-scoped conversation and navigates to it", async () => {
    const user = userEvent.setup();
    server.use(
      http.post("*/api/v1/tutor/conversations", async ({ request }) => {
        const body = (await request.json()) as { context_type: string; lesson_id?: string };
        expect(body.context_type).toBe("LESSON_HELP");
        expect(body.lesson_id).toBe("lesson-1");
        return HttpResponse.json({
          conversation_id: "conv-1",
          context_type: "LESSON_HELP",
          status: "ACTIVE",
          created_at: "2026-01-01T00:00:00Z",
          closed_at: null,
          lesson_id: "lesson-1",
          exercise_id: null,
          scenario_id: null,
          portfolio_id: null,
        });
      })
    );

    renderWithQuery(
      <AskTutorButton request={{ context_type: "LESSON_HELP", lesson_id: "lesson-1" }} label="Ask the tutor" />
    );

    await user.click(screen.getByRole("button", { name: "Ask the tutor" }));

    await waitFor(() => expect(pushMock).toHaveBeenCalledWith("/tutor/conv-1"));
  });
});

import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { Suspense } from "react";
import { describe, expect, it } from "vitest";

import TutorConversationPage from "@/app/(protected)/tutor/[conversationId]/page";
import { server } from "@/tests/mocks/server";
import { act, renderWithProviders, screen, waitFor } from "@/tests/test-utils";

const CONVERSATION_ID = "conv-1";
const HEBREW_QUESTION = "מה זה פיזור סיכונים בתיק השקעות?";
const MIXED_QUESTION = "מה ההבדל בין ETF לבין S&P 500 ב-2024?";

function mockConversation() {
  server.use(
    http.get("*/api/v1/tutor/conversations/:id", () =>
      HttpResponse.json({
        closed_at: null,
        context_type: "GENERAL_EDUCATION",
        conversation_id: CONVERSATION_ID,
        created_at: "2026-01-01T00:00:00Z",
        exercise_id: null,
        lesson_id: null,
        portfolio_id: null,
        scenario_id: null,
        status: "ACTIVE",
      })
    ),
    http.get("*/api/v1/tutor/conversations/:id/messages", () => HttpResponse.json([]))
  );
}

async function renderPage() {
  // `use(params)` suspends on its first pass (a promise's `.then`
  // callback is always deferred by at least one microtask, even for
  // an already-resolved promise). `render()` wraps itself in a
  // *synchronous* `act()`, which is too early to catch that retry -
  // the render call itself must be inside an `await act(async ...)`
  // for the Suspense boundary to properly re-render once the promise
  // settles.
  let result!: ReturnType<typeof renderWithProviders>;
  await act(async () => {
    result = renderWithProviders(
      <Suspense fallback={null}>
        <TutorConversationPage params={Promise.resolve({ conversationId: CONVERSATION_ID })} />
      </Suspense>
    );
  });
  return result;
}

describe("Tutor conversation composer: Hebrew and mixed-language input", () => {
  it("switches the textarea to rtl as soon as Hebrew characters are typed, and back to ltr for English", async () => {
    mockConversation();
    const user = userEvent.setup();
    await renderPage();

    const textarea = await screen.findByLabelText("Ask a question");
    expect(textarea).toHaveAttribute("dir", "ltr");

    await user.type(textarea, HEBREW_QUESTION);
    expect(textarea).toHaveAttribute("dir", "rtl");

    await user.clear(textarea);
    await user.type(textarea, "What is diversification?");
    expect(textarea).toHaveAttribute("dir", "ltr");
  });

  it("submits a Hebrew question to the API completely unchanged - no transliteration, no mangled Unicode", async () => {
    mockConversation();
    let capturedQuestion: string | null = null;
    server.use(
      http.post("*/api/v1/tutor/conversations/:id/messages", async ({ request }) => {
        const body = (await request.json()) as { question: string };
        capturedQuestion = body.question;
        return HttpResponse.json({
          answer_markdown: "תשובה לדוגמה.",
          citations: [],
          created_at: "2026-01-01T00:01:00Z",
          grounding_status: "GROUNDED",
          guardrail_action: "ALLOW",
          request_category: "ALLOWED_EDUCATION",
          status: "GENERATED",
        });
      })
    );

    const user = userEvent.setup();
    await renderPage();

    const textarea = await screen.findByLabelText("Ask a question");
    await user.type(textarea, HEBREW_QUESTION);
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => expect(capturedQuestion).toBe(HEBREW_QUESTION));
  });

  it("preserves mixed Hebrew/English/numeral text (tickers, years) exactly, and treats it as rtl since it contains Hebrew", async () => {
    mockConversation();
    let capturedQuestion: string | null = null;
    server.use(
      http.post("*/api/v1/tutor/conversations/:id/messages", async ({ request }) => {
        const body = (await request.json()) as { question: string };
        capturedQuestion = body.question;
        return HttpResponse.json({
          answer_markdown: "answer",
          citations: [],
          created_at: "2026-01-01T00:01:00Z",
          grounding_status: "GROUNDED",
          guardrail_action: "ALLOW",
          request_category: "ALLOWED_EDUCATION",
          status: "GENERATED",
        });
      })
    );

    const user = userEvent.setup();
    await renderPage();

    const textarea = await screen.findByLabelText("Ask a question");
    await user.type(textarea, MIXED_QUESTION);
    expect(textarea).toHaveAttribute("dir", "rtl");

    await user.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(capturedQuestion).toBe(MIXED_QUESTION));
  });
});

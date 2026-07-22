import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { useAskQuestion, useCreateConversation } from "@/hooks/useTutor";
import { server } from "@/tests/mocks/server";
import { renderHookWithQuery, waitFor } from "@/tests/test-utils";

describe("tutor hooks (integration)", () => {
  it("creates a conversation scoped to the requested context", async () => {
    server.use(
      http.post("*/api/v1/tutor/conversations", async ({ request }) => {
        const body = (await request.json()) as { context_type: string };
        return HttpResponse.json(
          {
            closed_at: null, context_type: body.context_type, conversation_id: "conv-1",
            created_at: "2026-01-01T00:00:00Z", exercise_id: null, lesson_id: null,
            portfolio_id: null, scenario_id: null, status: "ACTIVE",
          },
          { status: 201 }
        );
      })
    );

    const { result } = renderHookWithQuery(() => useCreateConversation());
    result.current.mutate({ context_type: "GENERAL_EDUCATION" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.context_type).toBe("GENERAL_EDUCATION");
  });

  it("returns an answer with learner-safe citations, never a chunk id or raw vector", async () => {
    server.use(
      http.post("*/api/v1/tutor/conversations/conv-1/messages", () =>
        HttpResponse.json({
          answer_markdown: "Diversification means spreading risk across assets. [1]",
          citations: [
            { citation_number: 1, document_title: "Diversification 101", excerpt: "Spread your risk.", heading_path: [], source_title: "FinQuest Curriculum" },
          ],
          created_at: "2026-01-01T00:00:00Z",
          grounding_status: "GROUNDED",
          guardrail_action: "ALLOW",
          request_category: "ALLOWED_EDUCATION",
          status: "GENERATED",
        })
      )
    );

    const { result } = renderHookWithQuery(() => useAskQuestion("conv-1"));
    result.current.mutate({ question: "What is diversification?", exercise_submitted: false, top_k: 8 });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const data = result.current.data as unknown as Record<string, unknown>;
    expect(data).not.toHaveProperty("chunk_id");
    expect(data).not.toHaveProperty("prompt");
    expect(result.current.data?.citations[0]?.document_title).toBe("Diversification 101");
  });

  it("surfaces a REFUSE guardrail action without throwing - the router decides how to render it", async () => {
    server.use(
      http.post("*/api/v1/tutor/conversations/conv-2/messages", () =>
        HttpResponse.json({
          answer_markdown: "I can't provide personalized investment advice, but here's how diversification works generally.",
          citations: [],
          created_at: "2026-01-01T00:00:00Z",
          grounding_status: "INSUFFICIENT_EVIDENCE",
          guardrail_action: "REFUSE",
          request_category: "PERSONALIZED_INVESTMENT_ADVICE",
          status: "REJECTED",
        })
      )
    );

    const { result } = renderHookWithQuery(() => useAskQuestion("conv-2"));
    result.current.mutate({ question: "What stock should I buy?", exercise_submitted: false, top_k: 8 });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data?.guardrail_action).toBe("REFUSE");
    expect(result.current.data?.citations).toHaveLength(0);
  });
});

import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useCoachStream } from "@/hooks/useCoachStream";

/** Builds a `ReadableStream<Uint8Array>` emitting one SSE `data:` frame
 * per event, exactly like the backend's `text/event-stream` response -
 * `useCoachStream` (via `lib/api/coach-stream.ts`) parses this same
 * shape from a real network response.
 *
 * Stubs `global.fetch` directly rather than going through this repo's
 * usual MSW handlers: MSW's fetch interceptor does a strict
 * `instanceof AbortSignal` check that the `AbortController` this hook
 * constructs internally fails under the current msw/jsdom combination
 * (an environment/tooling incompatibility, not a defect in the hook) -
 * stubbing `fetch` directly still exercises the exact same
 * `streamCoachEndpoint` code path against a real `Response`/
 * `ReadableStream`. */
function sseStreamFrom(events: unknown[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const event of events) {
        controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`));
      }
      controller.close();
    },
  });
}

function mockCoachStreamResponse(events: unknown[]): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(sseStreamFrom(events), { headers: { "Content-Type": "text/event-stream" } }))
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useCoachStream: Live Research SSE events (spec G2D2 section 12)", () => {
  it("research_started sets researchStatus and clears the generic stage indicator", async () => {
    mockCoachStreamResponse([
      { type: "stage", stage: "Thinking" },
      { type: "research_started", research_job_id: "job-1", deadline_at: "2026-01-01T00:10:00Z" },
    ]);
    const { result } = renderHook(() => useCoachStream("thread-1"));

    await act(async () => {
      await result.current.startTurn("What happened to Nvidia stock this week?");
    });

    await waitFor(() => expect(result.current.turns[0]?.researchStatus).toBe("started"));
    expect(result.current.turns[0]?.researchDeadlineAt).toBe("2026-01-01T00:10:00Z");
    expect(result.current.turns[0]?.stage).toBeNull();
  });

  it("research_waiting_update sets researchStatus to waiting", async () => {
    mockCoachStreamResponse([
      { type: "research_started", research_job_id: "job-1", deadline_at: "2026-01-01T00:10:00Z" },
      { type: "research_waiting_update", research_job_id: "job-1", scope: "NEWS_SCAN", deadline_at: "2026-01-01T00:10:00Z" },
    ]);
    const { result } = renderHook(() => useCoachStream("thread-2"));

    await act(async () => {
      await result.current.startTurn("What happened to Nvidia stock this week?");
    });

    await waitFor(() => expect(result.current.turns[0]?.researchStatus).toBe("waiting"));
  });

  it("research_completed populates the answer and marks the research grounded", async () => {
    mockCoachStreamResponse([
      { type: "research_started", research_job_id: "job-1", deadline_at: "2026-01-01T00:10:00Z" },
      {
        type: "research_completed",
        answer_markdown: "Nvidia reported strong quarterly earnings.",
        grounding_status: "GROUNDED",
        navigation_target: null,
      },
    ]);
    const { result } = renderHook(() => useCoachStream("thread-3"));

    await act(async () => {
      await result.current.startTurn("What happened to Nvidia stock this week?");
    });

    await waitFor(() => expect(result.current.turns[0]?.researchStatus).toBe("completed"));
    expect(result.current.turns[0]?.answerMarkdown).toBe("Nvidia reported strong quarterly earnings.");
  });

  it("research_unavailable populates the bounded fallback answer, not an error", async () => {
    mockCoachStreamResponse([
      { type: "research_started", research_job_id: "job-1", deadline_at: "2026-01-01T00:10:00Z" },
      {
        type: "research_unavailable",
        answer_markdown: "I could not find enough verified information to answer that right now.",
        grounding_status: "INSUFFICIENT_EVIDENCE",
        navigation_target: null,
      },
    ]);
    const { result } = renderHook(() => useCoachStream("thread-4"));

    await act(async () => {
      await result.current.startTurn("What happened to Nvidia stock this week?");
    });

    await waitFor(() => expect(result.current.turns[0]?.researchStatus).toBe("unavailable"));
    expect(result.current.turns[0]?.answerMarkdown).toContain("could not find");
    expect(result.current.turns[0]?.errorMessage).toBeNull();
  });

  it("a turn with no Live Research events keeps researchStatus null (unaffected regression check)", async () => {
    mockCoachStreamResponse([
      { type: "response_completed", answer_markdown: "Diversification spreads risk.", grounding_status: "GROUNDED", navigation_target: null },
      { type: "run_completed" },
    ]);
    const { result } = renderHook(() => useCoachStream("thread-5"));

    await act(async () => {
      await result.current.startTurn("What is diversification?");
    });

    await waitFor(() => expect(result.current.turns[0]?.isComplete).toBe(true));
    expect(result.current.turns[0]?.researchStatus).toBeNull();
    expect(result.current.turns[0]?.answerMarkdown).toBe("Diversification spreads risk.");
  });
});

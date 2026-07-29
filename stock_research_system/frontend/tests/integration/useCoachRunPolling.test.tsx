import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { useCoachRunPolling } from "@/hooks/useCoachRunPolling";
import { server } from "@/tests/mocks/server";
import { renderHookWithQuery, waitFor } from "@/tests/test-utils";

const RUN_ID = "run-1";

describe("useCoachRunPolling (spec G2D2/H1 correction pass, section 3)", () => {
  it("a WAITING_FOR_RESEARCH run starts polling", async () => {
    server.use(
      http.get(`*/api/v1/coach/runs/${RUN_ID}`, () =>
        HttpResponse.json({
          run_id: RUN_ID, thread_id: "thread-1", status: "WAITING_FOR_RESEARCH", intent: null, route: null,
          step_count: 3, maximum_steps: 30, created_at: "2026-01-01T00:00:00Z", started_at: "2026-01-01T00:00:00Z",
          waiting_at: "2026-01-01T00:00:01Z", completed_at: null, cancelled_at: null, failure_code: null,
        })
      )
    );

    const { result } = renderHookWithQuery(() => useCoachRunPolling(RUN_ID, { enabled: true }));

    await waitFor(() => expect(result.current.status).toBe("WAITING_FOR_RESEARCH"));
    expect(result.current.isPolling).toBe(true);
  });

  it("does not poll when disabled (e.g. a turn with no research interrupt)", async () => {
    const { result } = renderHookWithQuery(() => useCoachRunPolling(RUN_ID, { enabled: false }));
    expect(result.current.isPolling).toBe(false);
    expect(result.current.status).toBeNull();
  });

  it("a completed run displays the resumed answer from the RUN_COMPLETED event", async () => {
    server.use(
      http.get(`*/api/v1/coach/runs/${RUN_ID}`, () =>
        HttpResponse.json({
          run_id: RUN_ID, thread_id: "thread-1", status: "SUCCEEDED", intent: null, route: "GROUNDED_EXPLANATION",
          step_count: 6, maximum_steps: 30, created_at: "2026-01-01T00:00:00Z", started_at: "2026-01-01T00:00:00Z",
          waiting_at: "2026-01-01T00:00:01Z", completed_at: "2026-01-01T00:05:00Z", cancelled_at: null,
          failure_code: null,
        })
      ),
      http.get(`*/api/v1/coach/runs/${RUN_ID}/events`, () =>
        HttpResponse.json([
          {
            event_id: "event-1", event_type: "RUN_COMPLETED", sequence_number: 5,
            learner_message: "Run completed.", created_at: "2026-01-01T00:05:00Z",
            metadata: {
              answer_markdown: "Nvidia reported strong quarterly earnings.",
              citations: [{ citation_number: 1, source_title: "Nvidia Q3 report", document_title: "Nvidia" }],
              grounding_status: "GROUNDED", navigation_target: null,
            },
          },
        ])
      )
    );

    const { result } = renderHookWithQuery(() => useCoachRunPolling(RUN_ID, { enabled: true }));

    await waitFor(() => expect(result.current.status).toBe("SUCCEEDED"));
    await waitFor(() => expect(result.current.finalResponse?.answer_markdown).toBe("Nvidia reported strong quarterly earnings."));
    expect(result.current.isPolling).toBe(false);
    expect(result.current.errorKind).toBeNull();
  });

  it("a failed run displays a bounded error, never the raw failure_code", async () => {
    server.use(
      http.get(`*/api/v1/coach/runs/${RUN_ID}`, () =>
        HttpResponse.json({
          run_id: RUN_ID, thread_id: "thread-1", status: "FAILED", intent: null, route: null, step_count: 4,
          maximum_steps: 30, created_at: "2026-01-01T00:00:00Z", started_at: "2026-01-01T00:00:00Z",
          waiting_at: "2026-01-01T00:00:01Z", completed_at: "2026-01-01T00:02:00Z", cancelled_at: null,
          failure_code: "PROVIDER_OR_INFRASTRUCTURE_FAILURE",
        })
      )
    );

    const { result } = renderHookWithQuery(() => useCoachRunPolling(RUN_ID, { enabled: true }));

    await waitFor(() => expect(result.current.status).toBe("FAILED"));
    expect(result.current.errorKind).toBe("failure");
    expect(JSON.stringify(result.current)).not.toContain("PROVIDER_OR_INFRASTRUCTURE_FAILURE");
    expect(result.current.isPolling).toBe(false);
  });

  it("polling stops once the run reaches a terminal status", async () => {
    let callCount = 0;
    server.use(
      http.get(`*/api/v1/coach/runs/${RUN_ID}`, () => {
        callCount += 1;
        return HttpResponse.json({
          run_id: RUN_ID, thread_id: "thread-1", status: "SUCCEEDED", intent: null, route: null, step_count: 6,
          maximum_steps: 30, created_at: "2026-01-01T00:00:00Z", started_at: "2026-01-01T00:00:00Z",
          waiting_at: "2026-01-01T00:00:01Z", completed_at: "2026-01-01T00:05:00Z", cancelled_at: null,
          failure_code: null,
        });
      }),
      http.get(`*/api/v1/coach/runs/${RUN_ID}/events`, () => HttpResponse.json([]))
    );

    const { result } = renderHookWithQuery(() =>
      useCoachRunPolling(RUN_ID, { enabled: true, pollIntervalMs: 15 })
    );

    await waitFor(() => expect(result.current.status).toBe("SUCCEEDED"));
    const countAtCompletion = callCount;

    await new Promise((resolve) => setTimeout(resolve, 60));
    // No further polls after the run reached SUCCEEDED.
    expect(callCount).toBe(countAtCompletion);
  });

  it("polling stops on unmount", async () => {
    let callCount = 0;
    server.use(
      http.get(`*/api/v1/coach/runs/${RUN_ID}`, () => {
        callCount += 1;
        return HttpResponse.json({
          run_id: RUN_ID, thread_id: "thread-1", status: "WAITING_FOR_RESEARCH", intent: null, route: null,
          step_count: 3, maximum_steps: 30, created_at: "2026-01-01T00:00:00Z", started_at: "2026-01-01T00:00:00Z",
          waiting_at: "2026-01-01T00:00:01Z", completed_at: null, cancelled_at: null, failure_code: null,
        });
      })
    );

    const { result, unmount } = renderHookWithQuery(() =>
      useCoachRunPolling(RUN_ID, { enabled: true, pollIntervalMs: 15 })
    );
    await waitFor(() => expect(result.current.status).toBe("WAITING_FOR_RESEARCH"));

    unmount();
    const countAtUnmount = callCount;
    await new Promise((resolve) => setTimeout(resolve, 60));

    expect(callCount).toBe(countAtUnmount);
  });

  it("polling timeout is bounded - a run that never reaches a terminal status times out", async () => {
    server.use(
      http.get(`*/api/v1/coach/runs/${RUN_ID}`, () =>
        HttpResponse.json({
          run_id: RUN_ID, thread_id: "thread-1", status: "WAITING_FOR_RESEARCH", intent: null, route: null,
          step_count: 3, maximum_steps: 30, created_at: "2026-01-01T00:00:00Z", started_at: "2026-01-01T00:00:00Z",
          waiting_at: "2026-01-01T00:00:01Z", completed_at: null, cancelled_at: null, failure_code: null,
        })
      )
    );

    const { result } = renderHookWithQuery(() =>
      useCoachRunPolling(RUN_ID, { enabled: true, timeoutMs: 30, pollIntervalMs: 10 })
    );

    await waitFor(() => expect(result.current.timedOut).toBe(true));
    expect(result.current.isPolling).toBe(false);
    expect(result.current.errorKind).toBe("timeout");
  });
});

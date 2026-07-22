"use client";

/**
 * Server-Sent-Events client for `/api/v1/coach/.../stream` endpoints,
 * built on a plain authenticated `fetch()` - never the browser's native
 * `EventSource`, which cannot send an `Authorization` header. Parses
 * only the fixed, learner-safe event shapes the backend's
 * `event_stream.py` allow-list can ever produce; anything else is
 * ignored rather than crashing the UI.
 */
import { browserEnv } from "@/lib/environment";
import { getAccessTokenSnapshot } from "@/lib/auth/token-store";

export type CoachStreamEvent =
  | { type: "run_started"; run_id?: string }
  | { type: "stage"; stage: string }
  | { type: "intent"; intent: string | null }
  | { type: "route"; route: string }
  | { type: "retrieval_started" }
  | { type: "retrieval_completed" }
  | { type: "response_started" }
  | {
      type: "response_completed";
      answer_markdown: string | null;
      grounding_status: string | null;
      navigation_target: string | null;
    }
  | { type: "citation"; citation_number: number; source_title: string; document_title: string }
  | { type: "action_proposed"; proposal_id: string; title: string; description: string }
  | {
      type: "approval_required";
      proposal_id: string;
      title: string;
      description: string;
      reason: string;
      safe_parameters: Record<string, unknown>;
      expires_at: string | null;
    }
  | { type: "action_started" }
  | { type: "action_completed" }
  | { type: "run_completed"; run_id?: string; status?: string }
  | { type: "error"; message: string }
  | { type: "heartbeat" };

export interface StreamCoachOptions {
  onEvent: (event: CoachStreamEvent) => void;
  signal?: AbortSignal;
}

async function streamCoachEndpoint(
  path: string, body: unknown, options: StreamCoachOptions, extraHeaders: Record<string, string> = {}
): Promise<void> {
  const token = getAccessTokenSnapshot();
  const response = await fetch(new URL(path, browserEnv.NEXT_PUBLIC_FINQUEST_API_BASE_URL), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
      ...(token ? { Authorization: `Bearer ${token.accessToken}` } : {}),
      ...extraHeaders,
    },
    body: JSON.stringify(body),
    signal: options.signal,
  });

  if (!response.ok || !response.body) {
    options.onEvent({ type: "error", message: `The coach could not be reached (HTTP ${response.status}).` });
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }
      buffer += decoder.decode(value, { stream: true });

      const chunks = buffer.split("\n\n");
      buffer = chunks.pop() ?? "";
      for (const chunk of chunks) {
        const dataLine = chunk.split("\n").find((line) => line.startsWith("data: "));
        if (!dataLine) {
          continue;
        }
        try {
          const parsed = JSON.parse(dataLine.slice("data: ".length)) as CoachStreamEvent;
          options.onEvent(parsed);
        } catch {
          // A malformed line is dropped, never surfaced as raw text to the learner.
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}

export function streamStartRun(
  threadId: string,
  body: { user_input: string; context_references?: Record<string, string> },
  idempotencyKey: string,
  options: StreamCoachOptions
): Promise<void> {
  return streamCoachEndpoint(`/api/v1/coach/threads/${threadId}/runs/stream`, body, options, {
    "Idempotency-Key": idempotencyKey,
  });
}

export function streamResumeRun(
  runId: string,
  body: { proposal_id: string; decision: "APPROVE" | "REJECT" | "EDIT"; edited_parameters?: Record<string, unknown> },
  options: StreamCoachOptions
): Promise<void> {
  return streamCoachEndpoint(`/api/v1/coach/runs/${runId}/resume/stream`, body, options);
}

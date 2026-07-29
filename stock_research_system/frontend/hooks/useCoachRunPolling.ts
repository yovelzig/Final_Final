"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import type { LearningCoachEventResponse, LearningCoachRunResponse } from "@/types/api-schemas";

const TERMINAL_STATUSES = new Set<LearningCoachRunResponse["status"]>(["SUCCEEDED", "FAILED", "CANCELLED", "EXPIRED"]);
const POLL_INTERVAL_MS = 4_000;
/** Bounded, generous headroom over the backend's own research deadline
 * (`LiveResearchTriggerDependencies.research_deadline_seconds`, default
 * 600s) - a poll that outlives this is treated as timed out rather than
 * continuing forever. */
const DEFAULT_TIMEOUT_MS = 15 * 60 * 1000;

export interface CoachFinalResponse {
  answer_markdown?: string;
  citations?: unknown[];
  grounding_status?: string;
  navigation_target?: string | null;
}

export interface CoachRunPollState {
  status: LearningCoachRunResponse["status"] | null;
  isPolling: boolean;
  timedOut: boolean;
  finalResponse: CoachFinalResponse | null;
  errorKind: "failure" | "timeout" | null;
}

/** Bounded polling fallback for the async Live Research result delivery
 * (spec G2D2/H1 correction pass, section 3): the original SSE connection
 * closes the moment the Coach graph interrupts to wait for research,
 * since the eventual answer is delivered later by a background worker
 * resuming the graph, never through that already-closed HTTP response.
 * This hook polls the existing, authenticated, ownership-checked
 * `GET /api/v1/coach/runs/{run_id}` (and, once SUCCEEDED, `GET .../
 * events`) endpoints until the run reaches a terminal status, a bounded
 * timeout elapses, or the component unmounts - never indefinitely, and
 * there is no manual "resume" action anywhere in this flow. */
export function useCoachRunPolling(
  runId: string | null,
  {
    enabled,
    timeoutMs = DEFAULT_TIMEOUT_MS,
    pollIntervalMs = POLL_INTERVAL_MS,
  }: { enabled: boolean; timeoutMs?: number; pollIntervalMs?: number }
): CoachRunPollState {
  const [timedOut, setTimedOut] = useState(false);

  useEffect(() => {
    setTimedOut(false);
    if (!enabled || !runId) {
      return;
    }
    const timer = setTimeout(() => setTimedOut(true), timeoutMs);
    return () => clearTimeout(timer);
  }, [runId, enabled, timeoutMs]);

  const pollingActive = enabled && !!runId && !timedOut;

  const runQuery = useQuery({
    queryKey: queryKeys.coach.run(runId ?? ""),
    queryFn: () => apiClient.get<LearningCoachRunResponse>(`/api/v1/coach/runs/${runId}`),
    enabled: pollingActive,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (!status || TERMINAL_STATUSES.has(status)) {
        return false;
      }
      return pollIntervalMs;
    },
  });

  const status = runQuery.data?.status ?? null;
  const isTerminal = !!status && TERMINAL_STATUSES.has(status);

  const eventsQuery = useQuery({
    queryKey: queryKeys.coach.runEvents(runId ?? ""),
    queryFn: () => apiClient.get<LearningCoachEventResponse[]>(`/api/v1/coach/runs/${runId}/events`),
    enabled: !!runId && status === "SUCCEEDED",
  });

  const finalResponse = useMemo<CoachFinalResponse | null>(() => {
    if (status !== "SUCCEEDED" || !eventsQuery.data) {
      return null;
    }
    const runCompleted = [...eventsQuery.data].reverse().find((event) => event.event_type === "RUN_COMPLETED");
    if (!runCompleted?.metadata) {
      return null;
    }
    return runCompleted.metadata as CoachFinalResponse;
  }, [status, eventsQuery.data]);

  const errorKind =
    status === "FAILED" || status === "CANCELLED" || status === "EXPIRED"
      ? "failure" as const
      : timedOut && !isTerminal
        ? "timeout" as const
        : null;

  return {
    status,
    isPolling: pollingActive && !isTerminal,
    timedOut: timedOut && !isTerminal,
    finalResponse,
    errorKind,
  };
}

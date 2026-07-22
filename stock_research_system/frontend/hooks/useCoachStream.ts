"use client";

import { useCallback, useRef, useState } from "react";

import { generateIdempotencyKey } from "@/hooks/useLearningCoach";
import { type CoachStreamEvent, streamResumeRun, streamStartRun } from "@/lib/api/coach-stream";

export interface CoachTurn {
  id: string;
  runId: string | null;
  userInput: string;
  stage: string | null;
  answerMarkdown: string | null;
  citations: { citation_number: number; source_title: string; document_title: string }[];
  approvalRequest: Extract<CoachStreamEvent, { type: "approval_required" }> | null;
  approvalDecision: "APPROVE" | "REJECT" | "EDIT" | null;
  navigationTarget: string | null;
  errorMessage: string | null;
  isComplete: boolean;
}

function newTurn(userInput: string): CoachTurn {
  return {
    id: generateIdempotencyKey(), runId: null, userInput, stage: null, answerMarkdown: null, citations: [],
    approvalRequest: null, approvalDecision: null, navigationTarget: null, errorMessage: null, isComplete: false,
  };
}

/** Drives one learning-coach thread's turn-by-turn SSE conversation.
 * Owns no server-state cache of its own (React Query still owns thread/
 * run/event lookups) - this is purely the live, in-flight streaming
 * view for the turn currently in progress. */
export function useCoachStream(threadId: string) {
  const [turns, setTurns] = useState<CoachTurn[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const applyEvent = useCallback((turnId: string, event: CoachStreamEvent) => {
    setTurns((previous) =>
      previous.map((turn) => {
        if (turn.id !== turnId) {
          return turn;
        }
        switch (event.type) {
          case "run_started":
            return event.run_id ? { ...turn, runId: event.run_id } : turn;
          case "stage":
            return { ...turn, stage: event.stage };
          case "citation":
            return { ...turn, citations: [...turn.citations, event] };
          case "response_completed":
            return {
              ...turn,
              answerMarkdown: event.answer_markdown ?? turn.answerMarkdown,
              navigationTarget: event.navigation_target ?? turn.navigationTarget,
            };
          case "approval_required":
            return { ...turn, approvalRequest: event, stage: null };
          case "run_completed":
            return { ...turn, isComplete: true, stage: null };
          case "error":
            return { ...turn, errorMessage: event.message, isComplete: true, stage: null };
          default:
            return turn;
        }
      })
    );
  }, []);

  const startTurn = useCallback(
    async (userInput: string) => {
      const turn = newTurn(userInput);
      setTurns((previous) => [...previous, turn]);
      setIsStreaming(true);
      const controller = new AbortController();
      abortRef.current = controller;
      try {
        await streamStartRun(threadId, { user_input: userInput }, generateIdempotencyKey(), {
          signal: controller.signal,
          onEvent: (event) => applyEvent(turn.id, event),
        });
      } finally {
        setIsStreaming(false);
      }
    },
    [threadId, applyEvent]
  );

  const resumeTurn = useCallback(
    async (turnId: string, decision: "APPROVE" | "REJECT" | "EDIT") => {
      const turn = turns.find((candidate) => candidate.id === turnId);
      if (!turn?.approvalRequest || !turn.runId) {
        return;
      }
      setTurns((previous) =>
        previous.map((candidate) => (candidate.id === turnId ? { ...candidate, approvalDecision: decision } : candidate))
      );
      setIsStreaming(true);
      const controller = new AbortController();
      abortRef.current = controller;
      try {
        await streamResumeRun(
          turn.runId, { proposal_id: turn.approvalRequest.proposal_id, decision },
          { signal: controller.signal, onEvent: (event) => applyEvent(turnId, event) }
        );
      } finally {
        setIsStreaming(false);
      }
    },
    [turns, applyEvent]
  );

  const cancelStream = useCallback(() => {
    abortRef.current?.abort();
    setIsStreaming(false);
  }, []);

  return { turns, isStreaming, startTurn, resumeTurn, cancelStream };
}

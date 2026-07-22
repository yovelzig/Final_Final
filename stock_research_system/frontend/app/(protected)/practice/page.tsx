"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { AdaptiveAnswerResult } from "@/components/adaptive/AdaptiveAnswerResult";
import { RecommendationCard } from "@/components/adaptive/RecommendationCard";
import { SessionSummaryCard } from "@/components/adaptive/SessionSummaryCard";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { PageHeading } from "@/components/ui/PageHeading";
import { ExerciseAnswerInput } from "@/components/exercises/ExerciseAnswerInput";
import { buildAnswerPayload, isAnswerDraftComplete, useExerciseDraft } from "@/hooks/useExerciseDraft";
import { useAttempt } from "@/hooks/useCurriculum";
import {
  useAcceptDecision,
  useCompleteSession,
  useNextRecommendation,
  useSkipDecision,
  useStartDecisionExercise,
  useStartSession,
  useSubmitDecisionAnswer,
} from "@/hooks/useAdaptive";
import { queryKeys } from "@/lib/api/query-keys";
import type {
  AdaptiveDecisionResponse,
  ExerciseResponse,
  LessonResponse,
  SessionSummaryResponse,
} from "@/types/api-schemas";

type Phase =
  | "idle"
  | "loading-next"
  | "recommendation"
  | "terminal"
  | "in-progress"
  | "graded";

export default function PracticePage() {
  const queryClient = useQueryClient();

  const [phase, setPhase] = useState<Phase>("idle");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [decision, setDecision] = useState<AdaptiveDecisionResponse | null>(null);
  const [exercise, setExercise] = useState<ExerciseResponse | null>(null);
  const [lesson, setLesson] = useState<LessonResponse | null>(null);
  const [attemptId, setAttemptId] = useState<string | null>(null);
  const [summary, setSummary] = useState<SessionSummaryResponse | null>(null);

  const { draft, setDraft, reset: resetDraft } = useExerciseDraft();
  const attemptQuery = useAttempt(attemptId);

  const startSession = useStartSession();
  const nextRecommendation = useNextRecommendation();
  const acceptDecision = useAcceptDecision();
  const skipDecision = useSkipDecision();
  const startDecisionExercise = useStartDecisionExercise();
  const submitDecisionAnswer = useSubmitDecisionAnswer();
  const completeSession = useCompleteSession();

  const requestNext = (sid: string) => {
    setPhase("loading-next");
    setDecision(null);
    setExercise(null);
    setLesson(null);
    setAttemptId(null);
    resetDraft();
    nextRecommendation.mutate(sid, {
      onSuccess: (data) => {
        if (
          data.decision.recommendation_type === "SESSION_COMPLETE" ||
          data.decision.recommendation_type === "NO_ELIGIBLE_CONTENT"
        ) {
          setDecision(data.decision);
          setPhase("terminal");
          if (data.decision.recommendation_type === "SESSION_COMPLETE") {
            completeSession.mutate(sid, {
              onSuccess: (finished) => {
                setSummary(finished);
              },
            });
          }
          return;
        }
        setDecision(data.decision);
        setExercise(data.exercise);
        setLesson(data.lesson);
        setPhase("recommendation");
      },
    });
  };

  const handleStartPractice = () => {
    startSession.mutate(
      { session_type: "DAILY_PRACTICE" },
      {
        onSuccess: (session) => {
          setSessionId(session.session_id);
          setSummary(null);
          requestNext(session.session_id);
        },
      }
    );
  };

  const handleAccept = () => {
    if (!decision) return;
    acceptDecision.mutate(decision.decision_id, {
      onSuccess: (updated) => {
        setDecision(updated);
        startDecisionExercise.mutate(
          { decisionId: updated.decision_id, body: {} },
          {
            onSuccess: (attempt) => {
              setAttemptId(attempt.attempt_id);
              setPhase("in-progress");
            },
          }
        );
      },
    });
  };

  const handleSkip = () => {
    if (!decision || !sessionId) return;
    skipDecision.mutate(decision.decision_id, {
      onSuccess: () => requestNext(sessionId),
    });
  };

  const handleSubmitAnswer = () => {
    if (!decision || !exercise) return;
    submitDecisionAnswer.mutate(
      { decisionId: decision.decision_id, body: buildAnswerPayload(exercise.exercise_type, draft) },
      {
        onSuccess: (data) => {
          setSummary(data);
          if (attemptId) {
            void queryClient.invalidateQueries({ queryKey: queryKeys.curriculum.attempt(attemptId) });
          }
          setPhase("graded");
        },
      }
    );
  };

  const handleContinue = () => {
    if (!sessionId) return;
    requestNext(sessionId);
  };

  const handleEndSession = () => {
    if (!sessionId) return;
    completeSession.mutate(sessionId, {
      onSuccess: (data) => {
        setSummary(data);
        setPhase("terminal");
      },
    });
  };

  if (phase === "idle") {
    return (
      <div>
        <PageHeading title="Practice" description="A short, adaptive practice session picked just for you." />
        {startSession.isError ? <ErrorState error={startSession.error} onRetry={handleStartPractice} /> : null}
        <EmptyState
          title="Ready for today's practice?"
          description="We'll pick the next best thing for you to work on based on your progress."
          action={
            <Button onClick={handleStartPractice} isLoading={startSession.isPending}>
              Start practice session
            </Button>
          }
        />
      </div>
    );
  }

  return (
    <div>
      <PageHeading title="Practice" description="Adaptive daily practice." />

      {phase === "loading-next" ? (
        <div className="rounded-card border border-border bg-surface p-5" role="status" aria-label="Finding your next activity">
          <span className="sr-only">Finding your next activity…</span>
          <div className="h-24 animate-pulse rounded-md bg-slate-100" />
        </div>
      ) : null}

      {nextRecommendation.isError ? <ErrorState error={nextRecommendation.error} onRetry={() => sessionId && requestNext(sessionId)} /> : null}

      {phase === "recommendation" && decision ? (
        <RecommendationCard
          decision={decision}
          exercise={exercise}
          lesson={lesson}
          onAccept={handleAccept}
          onSkip={handleSkip}
          isAccepting={acceptDecision.isPending || startDecisionExercise.isPending}
          isSkipping={skipDecision.isPending}
        />
      ) : null}

      {(acceptDecision.isError || startDecisionExercise.isError) ? (
        <ErrorState error={acceptDecision.error ?? startDecisionExercise.error} />
      ) : null}
      {skipDecision.isError ? <ErrorState error={skipDecision.error} /> : null}

      {phase === "in-progress" && exercise ? (
        // Keyed by decision_id (not exercise_id) - two consecutive
        // recommendations can reference the same exercise, and without a
        // key forcing a remount, React would reuse the previous decision's
        // radio/checkbox DOM nodes, leaving stale native checked state
        // behind.
        <div key={decision?.decision_id} className="rounded-card border border-border bg-surface p-5">
          <p className="mb-4 text-sm font-medium text-slate-900">{exercise.prompt}</p>
          <ExerciseAnswerInput
            exercise={exercise}
            draft={draft}
            onChange={setDraft}
            disabled={submitDecisionAnswer.isPending}
          />
          {submitDecisionAnswer.isError ? (
            <div className="mt-3">
              <ErrorState error={submitDecisionAnswer.error} onRetry={handleSubmitAnswer} />
            </div>
          ) : null}
          <Button
            className="mt-4"
            onClick={handleSubmitAnswer}
            isLoading={submitDecisionAnswer.isPending}
            disabled={!isAnswerDraftComplete(exercise.exercise_type, draft)}
          >
            Submit answer
          </Button>
        </div>
      ) : null}

      {phase === "graded" && exercise && summary ? (
        <div className="flex flex-col gap-4">
          <div className="rounded-card border border-border bg-surface p-5">
            <p className="mb-4 text-sm font-medium text-slate-900">{exercise.prompt}</p>
            {attemptQuery.data ? <AdaptiveAnswerResult attempt={attemptQuery.data} summary={summary} /> : null}
          </div>
          <div className="flex gap-2">
            <Button onClick={handleContinue}>Continue practicing</Button>
            <Button variant="ghost" onClick={handleEndSession} isLoading={completeSession.isPending}>
              End session
            </Button>
          </div>
        </div>
      ) : null}

      {phase === "terminal" && decision?.recommendation_type === "NO_ELIGIBLE_CONTENT" ? (
        <EmptyState
          title="Nothing to practice right now"
          description={decision.explanation}
          action={
            <Button variant="ghost" onClick={handleEndSession} isLoading={completeSession.isPending}>
              End session
            </Button>
          }
        />
      ) : null}

      {phase === "terminal" && summary ? (
        <SessionSummaryCard summary={summary} onStartNewSession={handleStartPractice} isStartingNewSession={startSession.isPending} />
      ) : null}
    </div>
  );
}

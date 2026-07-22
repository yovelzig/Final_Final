"use client";

import { useState } from "react";

import { DiagnosticResultSummary } from "@/components/adaptive/DiagnosticResultSummary";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { PageHeading } from "@/components/ui/PageHeading";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { ExerciseAnswerInput } from "@/components/exercises/ExerciseAnswerInput";
import { useExercise } from "@/hooks/useCurriculum";
import { buildAnswerPayload, isAnswerDraftComplete, useExerciseDraft } from "@/hooks/useExerciseDraft";
import {
  useCompleteDiagnostic,
  useStartDiagnostic,
  useStartDiagnosticItem,
  useSubmitDiagnosticResult,
} from "@/hooks/useDiagnostic";
import type { DiagnosticItemResponse, DiagnosticSummaryResponse } from "@/types/api-schemas";

function nextIncompleteItem(items: DiagnosticItemResponse[]): DiagnosticItemResponse | null {
  return items.slice().sort((a, b) => a.position - b.position).find((item) => item.completed_at === null) ?? null;
}

export default function DiagnosticPage() {
  const [summary, setSummary] = useState<DiagnosticSummaryResponse | null>(null);
  const [currentItem, setCurrentItem] = useState<DiagnosticItemResponse | null>(null);
  const [attemptId, setAttemptId] = useState<string | null>(null);
  const [isComplete, setIsComplete] = useState(false);

  const { draft, setDraft, reset: resetDraft } = useExerciseDraft();
  const exerciseQuery = useExercise(currentItem?.exercise_id ?? null);

  const startDiagnostic = useStartDiagnostic();
  const startItem = useStartDiagnosticItem();
  const submitResult = useSubmitDiagnosticResult();
  const completeDiagnostic = useCompleteDiagnostic();

  const beginItem = (assessmentId: string, item: DiagnosticItemResponse) => {
    setCurrentItem(item);
    resetDraft();
    startItem.mutate(
      { assessmentId, itemId: item.item_id, body: {} },
      { onSuccess: (attempt) => setAttemptId(attempt.attempt_id) }
    );
  };

  const handleStart = () => {
    startDiagnostic.mutate(
      { maximum_items: 10 },
      {
        onSuccess: (data) => {
          setSummary(data);
          const first = nextIncompleteItem(data.items);
          if (first) {
            beginItem(data.assessment.assessment_id, first);
          } else {
            setIsComplete(true);
          }
        },
      }
    );
  };

  const handleSubmit = () => {
    if (!summary || !currentItem || !exerciseQuery.data) return;
    submitResult.mutate(
      {
        assessmentId: summary.assessment.assessment_id,
        itemId: currentItem.item_id,
        body: buildAnswerPayload(exerciseQuery.data.exercise_type, draft),
      },
      {
        onSuccess: (data) => {
          setSummary(data);
          setAttemptId(null);
          const next = nextIncompleteItem(data.items);
          if (next) {
            beginItem(data.assessment.assessment_id, next);
          } else {
            completeDiagnostic.mutate(data.assessment.assessment_id, {
              onSuccess: (finished) => {
                setSummary(finished);
                setCurrentItem(null);
                setIsComplete(true);
              },
            });
          }
        },
      }
    );
  };

  if (!summary) {
    return (
      <div>
        <PageHeading title="Diagnostic" description="A short set of questions to find your starting point." />
        {startDiagnostic.isError ? <ErrorState error={startDiagnostic.error} onRetry={handleStart} /> : null}
        <EmptyState
          title="Find your starting point"
          description="Answer a short set of questions so we can tailor your practice to what you already know."
          action={
            <Button onClick={handleStart} isLoading={startDiagnostic.isPending}>
              Start diagnostic
            </Button>
          }
        />
      </div>
    );
  }

  if (isComplete) {
    return (
      <div>
        <PageHeading title="Diagnostic" />
        {completeDiagnostic.isError ? <ErrorState error={completeDiagnostic.error} /> : null}
        <DiagnosticResultSummary summary={summary} />
      </div>
    );
  }

  const completedCount = summary.items.filter((item) => item.completed_at !== null).length;

  return (
    <div>
      <PageHeading title="Diagnostic" />
      <div className="mb-4">
        <ProgressBar label="Progress" value={completedCount} max={summary.items.length} />
      </div>

      {(startItem.isError || exerciseQuery.isError) ? (
        <ErrorState error={startItem.error ?? exerciseQuery.error} />
      ) : null}

      {exerciseQuery.isPending || startItem.isPending ? (
        <div className="rounded-card border border-border bg-surface p-5" role="status" aria-label="Loading question">
          <span className="sr-only">Loading question…</span>
          <div className="h-24 animate-pulse rounded-md bg-slate-100" />
        </div>
      ) : exerciseQuery.data && attemptId ? (
        // Keyed by item_id (not exercise_id) - two diagnostic items can
        // reference the same underlying exercise, and without a key
        // forcing a remount, React would reuse the previous item's radio/
        // checkbox DOM nodes, leaving stale native checked state behind.
        <div key={currentItem?.item_id} className="rounded-card border border-border bg-surface p-5">
          <p className="mb-4 text-sm font-medium text-slate-900">{exerciseQuery.data.prompt}</p>
          <ExerciseAnswerInput
            exercise={exerciseQuery.data}
            draft={draft}
            onChange={setDraft}
            disabled={submitResult.isPending}
          />
          {submitResult.isError ? (
            <div className="mt-3">
              <ErrorState error={submitResult.error} onRetry={handleSubmit} />
            </div>
          ) : null}
          <Button
            className="mt-4"
            onClick={handleSubmit}
            isLoading={submitResult.isPending || completeDiagnostic.isPending}
            disabled={!isAnswerDraftComplete(exerciseQuery.data.exercise_type, draft)}
          >
            Submit answer
          </Button>
        </div>
      ) : null}
    </div>
  );
}

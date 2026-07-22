"use client";

import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { ErrorState } from "@/components/ui/ErrorState";
import { ExerciseResult } from "@/components/exercises/ExerciseResult";
import { MultipleChoiceInput } from "@/components/exercises/MultipleChoiceInput";
import { NumericAnswerInput } from "@/components/exercises/NumericAnswerInput";
import { OrderingInput } from "@/components/exercises/OrderingInput";
import { SingleSelectInput } from "@/components/exercises/SingleSelectInput";
import { TextResponseInput } from "@/components/exercises/TextResponseInput";
import { EMPTY_DRAFT, type AnswerDraft } from "@/components/exercises/types";
import { AskTutorButton } from "@/components/tutor/AskTutorButton";
import { parseNumericInput } from "@/lib/formatting";
import { useStartAttempt, useSubmitAnswer } from "@/hooks/useCurriculum";
import type { ExerciseResponse, SubmitAnswerRequest } from "@/types/api-schemas";

function buildSubmitPayload(exerciseType: ExerciseResponse["exercise_type"], draft: AnswerDraft): SubmitAnswerRequest {
  switch (exerciseType) {
    case "SINGLE_CHOICE":
    case "TRUE_FALSE":
    case "SCENARIO_DECISION":
      return { selected_option_ids: draft.selectedOptionIds };
    case "MULTIPLE_CHOICE":
      return { selected_option_ids: draft.selectedOptionIds };
    case "NUMERIC_INPUT":
      return { numeric_answer: parseNumericInput(draft.numericAnswer) };
    case "ORDERING":
      return { ordered_option_ids: draft.orderedOptionIds };
    case "TEXT_RESPONSE":
      return { text_answer: draft.textAnswer };
    default:
      return {};
  }
}

function isDraftComplete(exerciseType: ExerciseResponse["exercise_type"], draft: AnswerDraft): boolean {
  switch (exerciseType) {
    case "SINGLE_CHOICE":
    case "TRUE_FALSE":
    case "SCENARIO_DECISION":
      return draft.selectedOptionIds.length === 1;
    case "MULTIPLE_CHOICE":
      return draft.selectedOptionIds.length > 0;
    case "NUMERIC_INPUT":
      return parseNumericInput(draft.numericAnswer) !== null;
    case "ORDERING":
      return draft.orderedOptionIds.length > 0;
    case "TEXT_RESPONSE":
      return draft.textAnswer.trim().length > 0;
    default:
      return false;
  }
}

export function ExercisePlayer({ exercise }: { exercise: ExerciseResponse }) {
  const [draft, setDraft] = useState<AnswerDraft>(EMPTY_DRAFT);
  const startAttempt = useStartAttempt(exercise.exercise_id);
  const submitAnswer = useSubmitAnswer(startAttempt.data?.attempt_id ?? "");

  const handleStart = () => {
    if (startAttempt.data || startAttempt.isPending) return;
    startAttempt.mutate({});
  };

  const handleSubmit = () => {
    if (!startAttempt.data || submitAnswer.data) return;
    submitAnswer.mutate(buildSubmitPayload(exercise.exercise_type, draft));
  };

  const handleRetry = () => {
    setDraft(EMPTY_DRAFT);
    startAttempt.reset();
    submitAnswer.reset();
  };

  if (!startAttempt.data) {
    return (
      <div className="rounded-card border border-border bg-surface p-4">
        <p className="mb-3 text-sm text-slate-800">{exercise.prompt}</p>
        {startAttempt.isError ? <ErrorState error={startAttempt.error} onRetry={handleStart} /> : null}
        <div className="flex flex-wrap gap-2">
          <Button onClick={handleStart} isLoading={startAttempt.isPending}>
            Start exercise
          </Button>
          <AskTutorButton request={{ context_type: "EXERCISE_HELP", exercise_id: exercise.exercise_id }} />
        </div>
      </div>
    );
  }

  const isGraded = !!submitAnswer.data;
  const disabled = isGraded || submitAnswer.isPending;

  return (
    <div className="rounded-card border border-border bg-surface p-4">
      <p className="mb-4 text-sm font-medium text-slate-900">{exercise.prompt}</p>

      {exercise.exercise_type === "MULTIPLE_CHOICE" ? (
        <MultipleChoiceInput options={exercise.options} draft={draft} onChange={setDraft} disabled={disabled} />
      ) : exercise.exercise_type === "NUMERIC_INPUT" ? (
        <NumericAnswerInput draft={draft} onChange={setDraft} disabled={disabled} />
      ) : exercise.exercise_type === "ORDERING" ? (
        <OrderingInput options={exercise.options} draft={draft} onChange={setDraft} disabled={disabled} />
      ) : exercise.exercise_type === "TEXT_RESPONSE" ? (
        <TextResponseInput draft={draft} onChange={setDraft} disabled={disabled} />
      ) : (
        <SingleSelectInput options={exercise.options} draft={draft} onChange={setDraft} disabled={disabled} />
      )}

      {submitAnswer.isError ? (
        <div className="mt-3">
          <ErrorState error={submitAnswer.error} onRetry={handleSubmit} />
        </div>
      ) : null}

      {isGraded && submitAnswer.data ? (
        <div className="mt-4 flex flex-col gap-3">
          <ExerciseResult result={submitAnswer.data} />
          <Button variant="ghost" size="sm" onClick={handleRetry} className="self-start">
            Try another attempt
          </Button>
        </div>
      ) : (
        <Button
          onClick={handleSubmit}
          isLoading={submitAnswer.isPending}
          disabled={!isDraftComplete(exercise.exercise_type, draft)}
          className="mt-4"
        >
          Submit answer
        </Button>
      )}
    </div>
  );
}

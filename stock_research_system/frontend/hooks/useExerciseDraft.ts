"use client";

import { useState } from "react";

import { parseNumericInput } from "@/lib/formatting";
import { EMPTY_DRAFT, type AnswerDraft } from "@/components/exercises/types";
import type { ExerciseResponse, SubmitAnswerRequest } from "@/types/api-schemas";

export function buildAnswerPayload(
  exerciseType: ExerciseResponse["exercise_type"],
  draft: AnswerDraft
): SubmitAnswerRequest {
  switch (exerciseType) {
    case "SINGLE_CHOICE":
    case "TRUE_FALSE":
    case "SCENARIO_DECISION":
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

export function isAnswerDraftComplete(exerciseType: ExerciseResponse["exercise_type"], draft: AnswerDraft): boolean {
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

/** Owns the answer-draft state for one exercise attempt - shared
 * between the curriculum `ExercisePlayer` and the adaptive-practice
 * flow, which submit through different endpoints but need identical
 * input handling/validation. */
export function useExerciseDraft() {
  const [draft, setDraft] = useState<AnswerDraft>(EMPTY_DRAFT);
  const reset = () => setDraft(EMPTY_DRAFT);
  return { draft, setDraft, reset };
}

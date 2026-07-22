import { MultipleChoiceInput } from "@/components/exercises/MultipleChoiceInput";
import { NumericAnswerInput } from "@/components/exercises/NumericAnswerInput";
import { OrderingInput } from "@/components/exercises/OrderingInput";
import { SingleSelectInput } from "@/components/exercises/SingleSelectInput";
import { TextResponseInput } from "@/components/exercises/TextResponseInput";
import type { AnswerDraft } from "@/components/exercises/types";
import type { ExerciseResponse } from "@/types/api-schemas";

/** Dispatches to the correct input control for an exercise type. Pure
 * presentation - draft state and submission live in the caller
 * (`ExercisePlayer` for curriculum exercises, the adaptive-practice
 * flow for recommended exercises), since the two contexts submit
 * through different endpoints. */
export function ExerciseAnswerInput({
  exercise,
  draft,
  onChange,
  disabled,
}: {
  exercise: ExerciseResponse;
  draft: AnswerDraft;
  onChange: (draft: AnswerDraft) => void;
  disabled: boolean;
}) {
  switch (exercise.exercise_type) {
    case "MULTIPLE_CHOICE":
      return <MultipleChoiceInput options={exercise.options} draft={draft} onChange={onChange} disabled={disabled} />;
    case "NUMERIC_INPUT":
      return <NumericAnswerInput draft={draft} onChange={onChange} disabled={disabled} />;
    case "ORDERING":
      return <OrderingInput options={exercise.options} draft={draft} onChange={onChange} disabled={disabled} />;
    case "TEXT_RESPONSE":
      return <TextResponseInput draft={draft} onChange={onChange} disabled={disabled} />;
    default:
      return <SingleSelectInput options={exercise.options} draft={draft} onChange={onChange} disabled={disabled} />;
  }
}

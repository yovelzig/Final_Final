import { useId } from "react";

import { parseNumericInput } from "@/lib/formatting";
import type { AnswerDraft } from "@/components/exercises/types";

export function NumericAnswerInput({
  draft,
  onChange,
  disabled,
}: {
  draft: AnswerDraft;
  onChange: (draft: AnswerDraft) => void;
  disabled: boolean;
}) {
  const fieldId = useId();
  const isInvalid = draft.numericAnswer.trim() !== "" && parseNumericInput(draft.numericAnswer) === null;

  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={fieldId} className="text-sm font-medium text-slate-700">
        Your answer
      </label>
      <input
        id={fieldId}
        type="text"
        inputMode="decimal"
        disabled={disabled}
        value={draft.numericAnswer}
        aria-invalid={isInvalid || undefined}
        onChange={(event) => onChange({ ...draft, numericAnswer: event.target.value })}
        className={`w-full max-w-xs rounded-lg border px-3 py-2.5 text-sm ${isInvalid ? "border-danger" : "border-border"}`}
        placeholder="Enter a number"
      />
      {isInvalid ? <p className="text-xs font-medium text-danger">Enter a valid number.</p> : null}
    </div>
  );
}

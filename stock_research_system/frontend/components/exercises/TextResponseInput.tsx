import { TextareaField } from "@/components/ui/Textarea";
import type { AnswerDraft } from "@/components/exercises/types";

const MAX_LENGTH = 5000;

export function TextResponseInput({
  draft,
  onChange,
  disabled,
}: {
  draft: AnswerDraft;
  onChange: (draft: AnswerDraft) => void;
  disabled: boolean;
}) {
  return (
    <div>
      <TextareaField
        label="Your response"
        rows={5}
        maxLength={MAX_LENGTH}
        disabled={disabled}
        value={draft.textAnswer}
        onChange={(event) => onChange({ ...draft, textAnswer: event.target.value })}
        hint="This response type may not be automatically graded - it can still be submitted and reviewed."
      />
      <p className="mt-1 text-right text-xs text-muted">
        {draft.textAnswer.length}/{MAX_LENGTH}
      </p>
    </div>
  );
}

import type { ExerciseInputProps } from "@/components/exercises/types";

/** The backend does not tell the client how many options are expected
 * to be correct - so this never reveals or hints at an expected count. */
export function MultipleChoiceInput({ options, draft, onChange, disabled }: ExerciseInputProps) {
  const toggle = (optionId: string) => {
    const isSelected = draft.selectedOptionIds.includes(optionId);
    const next = isSelected
      ? draft.selectedOptionIds.filter((id) => id !== optionId)
      : [...draft.selectedOptionIds, optionId];
    onChange({ ...draft, selectedOptionIds: next });
  };

  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="sr-only">Choose all that apply</legend>
      {options.map((option) => {
        const checked = draft.selectedOptionIds.includes(option.option_id);
        return (
          <label
            key={option.option_id}
            className={`flex cursor-pointer items-center gap-3 rounded-lg border px-3 py-2.5 text-sm transition-colors ${
              checked ? "border-primary bg-primary-light" : "border-border hover:bg-slate-50"
            } ${disabled ? "cursor-not-allowed opacity-70" : ""}`}
          >
            <input
              type="checkbox"
              checked={checked}
              disabled={disabled}
              onChange={() => toggle(option.option_id)}
              className="h-4 w-4 accent-[#2D5BFF]"
            />
            <span className="text-slate-800">{option.content}</span>
          </label>
        );
      })}
    </fieldset>
  );
}

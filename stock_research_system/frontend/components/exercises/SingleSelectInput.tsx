import type { ExerciseInputProps } from "@/components/exercises/types";

/** Used for SINGLE_CHOICE, TRUE_FALSE, and SCENARIO_DECISION - all
 * three are a single-select radio group over the exercise's options. */
export function SingleSelectInput({ options, draft, onChange, disabled }: ExerciseInputProps) {
  const selected = draft.selectedOptionIds[0];

  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="sr-only">Choose one answer</legend>
      {options.map((option) => (
        <label
          key={option.option_id}
          className={`flex cursor-pointer items-center gap-3 rounded-lg border px-3 py-2.5 text-sm transition-colors ${
            selected === option.option_id ? "border-primary bg-primary-light" : "border-border hover:bg-slate-50"
          } ${disabled ? "cursor-not-allowed opacity-70" : ""}`}
        >
          <input
            type="radio"
            name="single-select-answer"
            value={option.option_id}
            checked={selected === option.option_id}
            disabled={disabled}
            onChange={() => onChange({ ...draft, selectedOptionIds: [option.option_id] })}
            className="h-4 w-4 accent-[#2D5BFF]"
          />
          <span className="text-slate-800">{option.content}</span>
        </label>
      ))}
    </fieldset>
  );
}

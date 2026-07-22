import { useEffect } from "react";

import type { ExerciseInputProps } from "@/components/exercises/types";

/** Keyboard-accessible reordering via explicit "Move up"/"Move down"
 * buttons - never relies on drag-and-drop as the only way to reorder. */
export function OrderingInput({ options, draft, onChange, disabled }: ExerciseInputProps) {
  useEffect(() => {
    if (draft.orderedOptionIds.length === 0 && options.length > 0) {
      onChange({
        ...draft,
        orderedOptionIds: [...options].sort((a, b) => a.position - b.position).map((option) => option.option_id),
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [options]);

  const optionsById = new Map(options.map((option) => [option.option_id, option]));
  const order = draft.orderedOptionIds.length > 0 ? draft.orderedOptionIds : options.map((option) => option.option_id);

  const move = (index: number, direction: -1 | 1) => {
    const targetIndex = index + direction;
    if (targetIndex < 0 || targetIndex >= order.length) return;
    const next = [...order];
    const [moved] = next.splice(index, 1);
    if (moved !== undefined) {
      next.splice(targetIndex, 0, moved);
    }
    onChange({ ...draft, orderedOptionIds: next });
  };

  return (
    <ol className="flex flex-col gap-2">
      {order.map((optionId, index) => {
        const option = optionsById.get(optionId);
        if (!option) return null;
        return (
          <li
            key={optionId}
            className="flex items-center justify-between gap-3 rounded-lg border border-border bg-white px-3 py-2.5 text-sm"
          >
            <span className="flex items-center gap-3">
              <span className="flex h-6 w-6 items-center justify-center rounded-full bg-slate-100 text-xs font-semibold text-slate-600">
                {index + 1}
              </span>
              {option.content}
            </span>
            <span className="flex gap-1">
              <button
                type="button"
                disabled={disabled || index === 0}
                onClick={() => move(index, -1)}
                aria-label={`Move "${option.content}" up`}
                className="rounded-md border border-border px-2 py-1 text-xs font-medium text-slate-600 hover:bg-slate-100 disabled:opacity-40"
              >
                ↑ Up
              </button>
              <button
                type="button"
                disabled={disabled || index === order.length - 1}
                onClick={() => move(index, 1)}
                aria-label={`Move "${option.content}" down`}
                className="rounded-md border border-border px-2 py-1 text-xs font-medium text-slate-600 hover:bg-slate-100 disabled:opacity-40"
              >
                ↓ Down
              </button>
            </span>
          </li>
        );
      })}
    </ol>
  );
}

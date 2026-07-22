/** Small accessibility helpers shared across components. */

let idCounter = 0;

/** A stable, unique-enough id for wiring `aria-describedby`/`htmlFor`
 * pairs when React's `useId` isn't convenient (e.g. outside a
 * component). Prefer `useId` inside components. */
export function generateA11yId(prefix: string): string {
  idCounter += 1;
  return `${prefix}-${idCounter}`;
}

/** Builds a screen-reader-only visually-hidden class list (paired with
 * the `.sr-only` utility class defined in `globals.css`). */
export const SR_ONLY_CLASS = "sr-only";

/** Returns a human-readable, screen-reader-friendly announcement for a
 * grading result - used to populate an `aria-live` region so a learner
 * using a screen reader hears the outcome without needing to find it
 * visually. */
export function gradingAnnouncement(isCorrect: boolean | null, scoreLabel?: string): string {
  if (isCorrect === null) {
    return "Your answer was submitted and is pending review.";
  }
  const base = isCorrect ? "Correct." : "Not quite right.";
  return scoreLabel ? `${base} ${scoreLabel}` : base;
}

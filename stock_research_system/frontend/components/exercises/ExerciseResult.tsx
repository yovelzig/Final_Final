import { Badge } from "@/components/ui/Badge";
import { gradingAnnouncement } from "@/lib/accessibility";
import type { SubmitAnswerResponse } from "@/types/api-schemas";

/** Renders only backend-provided grading data - never recomputes or
 * guesses correctness/score itself. */
export function ExerciseResult({ result }: { result: SubmitAnswerResponse }) {
  const { attempt, updated_mastery, updated_progress } = result;
  const scoreLabel =
    attempt.score !== null ? `Score: ${attempt.score} out of ${attempt.maximum_score}.` : undefined;

  return (
    <div className="rounded-lg border border-border bg-slate-50 p-4">
      <div role="status" aria-live="polite" className="sr-only">
        {gradingAnnouncement(attempt.is_correct, scoreLabel)}
      </div>

      <div className="flex items-center gap-2">
        {attempt.is_correct === true ? (
          <Badge tone="success">Correct</Badge>
        ) : attempt.is_correct === false ? (
          <Badge tone="danger">Not quite right</Badge>
        ) : (
          <Badge tone="neutral">Pending review</Badge>
        )}
        {attempt.score !== null ? (
          <span className="text-sm text-slate-700">
            {attempt.score} / {attempt.maximum_score}
          </span>
        ) : null}
      </div>

      {updated_mastery.length > 0 ? (
        <p className="mt-3 text-xs text-muted">Skill mastery updated for {updated_mastery.length} skill(s).</p>
      ) : null}
      {updated_progress ? (
        <p className="mt-1 text-xs text-muted">
          Lesson progress: {Math.round(updated_progress.completion_percentage * 100)}% complete.
        </p>
      ) : null}
    </div>
  );
}

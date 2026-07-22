import { Badge } from "@/components/ui/Badge";
import { gradingAnnouncement } from "@/lib/accessibility";
import type { AttemptResponse, SessionSummaryResponse } from "@/types/api-schemas";

/** Renders only backend-provided grading data for the just-answered
 * adaptive-practice exercise - never recomputes correctness. */
export function AdaptiveAnswerResult({
  attempt,
  summary,
}: {
  attempt: AttemptResponse;
  summary: SessionSummaryResponse;
}) {
  const skillsUpdated = Object.keys(summary.mastery_changes).length;
  const scoreLabel = attempt.score !== null ? `Score: ${attempt.score} out of ${attempt.maximum_score}.` : undefined;

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

      {skillsUpdated > 0 ? (
        <p className="mt-3 text-xs text-muted">Skill mastery updated for {skillsUpdated} skill(s).</p>
      ) : null}
    </div>
  );
}

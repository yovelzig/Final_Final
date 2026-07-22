import { Badge, type BadgeTone } from "@/components/ui/Badge";
import { Card, CardHeader, CardTitle } from "@/components/ui/Card";
import type { components } from "@/types/generated-api";
import type { DiagnosticSummaryResponse } from "@/types/api-schemas";

type DiagnosticSkillResult = components["schemas"]["DiagnosticSkillResult"];

const RESULT_LABELS: Record<DiagnosticSkillResult, string> = {
  NOT_ASSESSED: "Not assessed",
  NEEDS_FOUNDATION: "Needs foundation",
  DEVELOPING: "Developing",
  READY: "Ready",
  STRONG: "Strong",
};

const RESULT_TONES: Record<DiagnosticSkillResult, BadgeTone> = {
  NOT_ASSESSED: "neutral",
  NEEDS_FOUNDATION: "danger",
  DEVELOPING: "warning",
  READY: "primary",
  STRONG: "success",
};

/** Displays only backend-computed skill-readiness results, grouped by
 * level - the backend does not expose learner-facing skill names, so
 * this summarizes by count rather than inventing labels. */
export function DiagnosticResultSummary({ summary }: { summary: DiagnosticSummaryResponse }) {
  const counts = new Map<DiagnosticSkillResult, number>();
  for (const result of Object.values(summary.skill_results)) {
    counts.set(result, (counts.get(result) ?? 0) + 1);
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Diagnostic complete</CardTitle>
      </CardHeader>

      <p className="text-sm text-muted">
        You completed {summary.items.filter((item) => item.completed_at !== null).length} of{" "}
        {summary.items.length} questions.
      </p>

      <div className="mt-4 flex flex-wrap gap-2">
        {(Object.keys(RESULT_LABELS) as DiagnosticSkillResult[])
          .filter((level) => (counts.get(level) ?? 0) > 0)
          .map((level) => (
            <Badge key={level} tone={RESULT_TONES[level]}>
              {RESULT_LABELS[level]}: {counts.get(level)}
            </Badge>
          ))}
      </div>

      {summary.recommended_starting_skill_ids.length > 0 ? (
        <p className="mt-4 text-xs text-muted">
          We&apos;ve identified {summary.recommended_starting_skill_ids.length} skill area(s) to start with in
          your practice sessions.
        </p>
      ) : null}
    </Card>
  );
}

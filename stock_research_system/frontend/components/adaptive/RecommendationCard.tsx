import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { RECOMMENDATION_REASON_LABELS, RECOMMENDATION_TYPE_LABELS } from "@/components/adaptive/labels";
import type { AdaptiveDecisionResponse, ExerciseResponse, LessonResponse } from "@/types/api-schemas";

export function RecommendationCard({
  decision,
  exercise,
  lesson,
  onAccept,
  onSkip,
  isAccepting,
  isSkipping,
}: {
  decision: AdaptiveDecisionResponse;
  exercise: ExerciseResponse | null;
  lesson: LessonResponse | null;
  onAccept: () => void;
  onSkip: () => void;
  isAccepting: boolean;
  isSkipping: boolean;
}) {
  return (
    <div className="rounded-card border border-border bg-surface p-5">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Badge tone="primary">{RECOMMENDATION_TYPE_LABELS[decision.recommendation_type]}</Badge>
        {decision.reason_codes.map((reason) => (
          <Badge key={reason} tone="neutral">
            {RECOMMENDATION_REASON_LABELS[reason]}
          </Badge>
        ))}
      </div>

      <p className="text-sm text-slate-800">{decision.explanation}</p>

      {lesson ? <p className="mt-2 text-xs text-muted">From: {lesson.title}</p> : null}
      {exercise ? <p className="mt-3 text-sm font-medium text-slate-900">{exercise.prompt}</p> : null}

      <div className="mt-4 flex gap-2">
        <Button onClick={onAccept} isLoading={isAccepting} disabled={isSkipping}>
          Start this
        </Button>
        <Button variant="ghost" onClick={onSkip} isLoading={isSkipping} disabled={isAccepting}>
          Skip
        </Button>
      </div>
    </div>
  );
}

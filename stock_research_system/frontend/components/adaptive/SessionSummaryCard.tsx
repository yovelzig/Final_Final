import { Button } from "@/components/ui/Button";
import { Card, CardHeader, CardTitle } from "@/components/ui/Card";
import type { SessionSummaryResponse } from "@/types/api-schemas";

export function SessionSummaryCard({
  summary,
  onStartNewSession,
  isStartingNewSession,
}: {
  summary: SessionSummaryResponse;
  onStartNewSession: () => void;
  isStartingNewSession: boolean;
}) {
  const { session, mastery_changes, reviews_scheduled } = summary;
  const skillsUpdated = Object.keys(mastery_changes).length;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Session complete</CardTitle>
      </CardHeader>

      <dl className="grid grid-cols-2 gap-4 text-sm sm:grid-cols-4">
        <div>
          <dt className="text-xs text-muted">Completed</dt>
          <dd className="text-lg font-semibold text-slate-900">{session.completed_item_count}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Correct</dt>
          <dd className="text-lg font-semibold text-slate-900">{session.correct_item_count}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Score</dt>
          <dd className="text-lg font-semibold text-slate-900">
            {session.total_score}/{session.maximum_score}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Skills updated</dt>
          <dd className="text-lg font-semibold text-slate-900">{skillsUpdated}</dd>
        </div>
      </dl>

      {reviews_scheduled.length > 0 ? (
        <p className="mt-4 text-xs text-muted">
          {reviews_scheduled.length} review{reviews_scheduled.length === 1 ? "" : "s"} scheduled for later.
        </p>
      ) : null}

      <Button className="mt-5" onClick={onStartNewSession} isLoading={isStartingNewSession}>
        Start another session
      </Button>
    </Card>
  );
}

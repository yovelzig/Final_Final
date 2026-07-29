"use client";

import Link from "next/link";

import { ApprovalCard } from "@/components/coach/ApprovalCard";
import { Button } from "@/components/ui/Button";
import { LessonMarkdown } from "@/components/learning/LessonMarkdown";
import { detectTextDirection } from "@/lib/i18n/config";
import type { CoachTurn } from "@/hooks/useCoachStream";
import { useCoachRunPolling } from "@/hooks/useCoachRunPolling";
import { useDictionary } from "@/providers/LocaleProvider";

type LearnerCitation = CoachTurn["citations"][number];

function learnerSafeCitations(value: unknown): LearnerCitation[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((citation) => {
    if (
      typeof citation !== "object" || citation === null ||
      typeof (citation as Record<string, unknown>).citation_number !== "number" ||
      typeof (citation as Record<string, unknown>).source_title !== "string"
    ) return [];
    const safe = citation as Record<string, unknown>;
    return [{
      citation_number: safe.citation_number as number,
      source_title: typeof safe.publisher === "string" ? safe.publisher : safe.source_title as string,
      document_title: typeof safe.document_title === "string" ? safe.document_title : safe.source_title as string,
    }];
  });
}

/** Renders one Coach turn, including the bounded polling fallback (spec
 * G2D2/H1 correction pass, section 3) for a turn whose original SSE
 * connection closed while waiting on Live Research - polling is scoped
 * to this one turn's `runId` and stops automatically on completion,
 * failure, timeout, or this component unmounting (e.g. the learner
 * navigates away). */
export function CoachTurnView({
  turn,
  isStreaming,
  onApprove,
  onReject,
}: {
  turn: CoachTurn;
  isStreaming: boolean;
  onApprove: () => void;
  onReject: () => void;
}) {
  const t = useDictionary();

  const pollingEnabled = turn.researchStatus === "waiting" && !turn.isComplete;
  const poll = useCoachRunPolling(turn.runId, { enabled: pollingEnabled });

  const polledResponse = poll.finalResponse;
  const completedThroughPolling = polledResponse !== null;
  const answerMarkdown = completedThroughPolling
    ? polledResponse.answer_markdown ?? null
    : turn.answerMarkdown;
  const citations = completedThroughPolling
    ? learnerSafeCitations(polledResponse.citations)
    : turn.citations;
  const errorMessage = turn.errorMessage ??
    (poll.errorKind === "failure"
      ? t.coach.researchFailed
      : poll.errorKind === "timeout"
        ? t.coach.researchTimedOut
        : null);

  return (
    <div className="flex flex-col gap-2">
      <div
        dir={detectTextDirection(turn.userInput)}
        className="ms-auto max-w-2xl rounded-card border border-primary/20 bg-primary-light p-4 text-sm text-slate-800"
      >
        {turn.userInput}
      </div>

      {turn.stage && !turn.isComplete ? (
        <p className="text-xs text-muted" role="status">
          {turn.stage}&hellip;
        </p>
      ) : null}

      {turn.researchStatus === "started" || (turn.researchStatus === "waiting" && poll.isPolling) ? (
        <p className="text-xs text-muted" role="status">
          {turn.researchStatus === "started" ? t.coach.researchStarted : t.coach.researchWaiting}
        </p>
      ) : null}

      {poll.timedOut ? (
        <p className="text-xs text-muted" role="status">
          {t.coach.researchTimedOut}
        </p>
      ) : null}

      {errorMessage ? (
        <div className="max-w-2xl rounded-card border border-danger/30 bg-danger-light p-4 text-sm text-danger">
          {errorMessage}
        </div>
      ) : null}

      {answerMarkdown ? (
        <div className="max-w-2xl rounded-card border border-border bg-surface p-4 text-sm">
          <LessonMarkdown content={answerMarkdown} />
          {citations.length > 0 ? (
            <div className="mt-3 border-t border-border pt-2">
              <p className="text-xs font-medium text-muted">{t.tutor.sourcesLabel}</p>
              <ul className="mt-1 flex flex-col gap-1 text-xs text-muted">
                {citations.map((citation) => (
                  <li key={citation.citation_number}>
                    [{citation.citation_number}] {citation.document_title} &mdash; {citation.source_title}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : null}

      {turn.approvalRequest ? (
        <div className="max-w-2xl">
          <ApprovalCard
            request={turn.approvalRequest}
            decision={turn.approvalDecision}
            isSubmitting={isStreaming && turn.approvalDecision !== null}
            onApprove={onApprove}
            onReject={onReject}
          />
        </div>
      ) : null}

      {turn.navigationTarget ? (
        <Link href={turn.navigationTarget} className="self-start">
          <Button size="sm" variant="secondary">
            {t.coach.continueLabel}
          </Button>
        </Link>
      ) : null}
    </div>
  );
}

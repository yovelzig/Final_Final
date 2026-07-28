"use client";

import { use, useState } from "react";
import Link from "next/link";

import { ApprovalCard } from "@/components/coach/ApprovalCard";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { ErrorState } from "@/components/ui/ErrorState";
import { PageHeading } from "@/components/ui/PageHeading";
import { LoadingSkeletonCard } from "@/components/ui/Skeleton";
import { TextareaField } from "@/components/ui/Textarea";
import { LessonMarkdown } from "@/components/learning/LessonMarkdown";
import { detectTextDirection } from "@/lib/i18n/config";
import { useCloseCoachThread, useCoachThread } from "@/hooks/useLearningCoach";
import { useCoachStream } from "@/hooks/useCoachStream";
import { useDictionary } from "@/providers/LocaleProvider";

export default function CoachThreadPage({ params }: { params: Promise<{ threadId: string }> }) {
  const { threadId } = use(params);
  const t = useDictionary();
  const threadQuery = useCoachThread(threadId);
  const closeThread = useCloseCoachThread();
  const { turns, isStreaming, startTurn, resumeTurn } = useCoachStream(threadId);

  const [userInput, setUserInput] = useState("");

  if (threadQuery.isPending) {
    return <LoadingSkeletonCard />;
  }
  if (threadQuery.isError) {
    return <ErrorState error={threadQuery.error} onRetry={() => void threadQuery.refetch()} />;
  }

  const thread = threadQuery.data;
  const isClosed = thread.status !== "ACTIVE";

  const handleSend = (event: React.FormEvent) => {
    event.preventDefault();
    // Unicode question text (Hebrew, English, or mixed) is trimmed of
    // surrounding whitespace only, then sent to the run stream as-is.
    const trimmed = userInput.trim();
    if (!trimmed || isStreaming || isClosed) return;
    setUserInput("");
    void startTurn(trimmed);
  };

  return (
    <div>
      <PageHeading
        title={thread.title}
        action={
          !isClosed ? (
            <Button variant="ghost" onClick={() => closeThread.mutate(threadId)} isLoading={closeThread.isPending}>
              {t.coach.closeConversation}
            </Button>
          ) : (
            <Badge tone="neutral">{t.coach.closed}</Badge>
          )
        }
      />

      <div className="flex flex-col gap-4" aria-live="polite">
        {turns.length === 0 ? <p className="text-sm text-muted">{t.coach.startPrompt}</p> : null}

        {turns.map((turn) => (
          <div key={turn.id} className="flex flex-col gap-2">
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

            {turn.errorMessage ? (
              <div className="max-w-2xl rounded-card border border-danger/30 bg-danger-light p-4 text-sm text-danger">
                {turn.errorMessage}
              </div>
            ) : null}

            {turn.answerMarkdown ? (
              <div className="max-w-2xl rounded-card border border-border bg-surface p-4 text-sm">
                <LessonMarkdown content={turn.answerMarkdown} />
                {turn.citations.length > 0 ? (
                  <div className="mt-3 border-t border-border pt-2">
                    <p className="text-xs font-medium text-muted">{t.tutor.sourcesLabel}</p>
                    <ul className="mt-1 flex flex-col gap-1 text-xs text-muted">
                      {turn.citations.map((citation) => (
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
                  onApprove={() => void resumeTurn(turn.id, "APPROVE")}
                  onReject={() => void resumeTurn(turn.id, "REJECT")}
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
        ))}

        {!isClosed ? (
          <form onSubmit={handleSend} className="flex flex-col gap-3 rounded-card border border-border bg-surface p-4">
            <TextareaField
              label={t.coach.askLabel}
              value={userInput}
              onChange={(event) => setUserInput(event.target.value)}
              dir={detectTextDirection(userInput)}
              rows={3}
              disabled={isStreaming}
            />
            <Button type="submit" isLoading={isStreaming} disabled={!userInput.trim()} className="self-start">
              {t.coach.send}
            </Button>
          </form>
        ) : (
          <p className="text-sm text-muted">{t.coach.conversationClosedNotice}</p>
        )}
      </div>
    </div>
  );
}

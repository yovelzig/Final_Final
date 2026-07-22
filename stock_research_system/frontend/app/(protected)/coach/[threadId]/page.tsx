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
import { useCloseCoachThread, useCoachThread } from "@/hooks/useLearningCoach";
import { useCoachStream } from "@/hooks/useCoachStream";

export default function CoachThreadPage({ params }: { params: Promise<{ threadId: string }> }) {
  const { threadId } = use(params);
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
              Close conversation
            </Button>
          ) : (
            <Badge tone="neutral">Closed</Badge>
          )
        }
      />

      <div className="flex flex-col gap-4" aria-live="polite">
        {turns.length === 0 ? (
          <p className="text-sm text-muted">Ask a question below to get started.</p>
        ) : null}

        {turns.map((turn) => (
          <div key={turn.id} className="flex flex-col gap-2">
            <div className="ml-auto max-w-2xl rounded-card border border-primary/20 bg-primary-light p-4 text-sm text-slate-800">
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
                  <ul className="mt-3 flex flex-col gap-1 border-t border-border pt-2 text-xs text-muted">
                    {turn.citations.map((citation) => (
                      <li key={citation.citation_number}>
                        [{citation.citation_number}] {citation.document_title} &mdash; {citation.source_title}
                      </li>
                    ))}
                  </ul>
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
                  Continue
                </Button>
              </Link>
            ) : null}
          </div>
        ))}

        {!isClosed ? (
          <form onSubmit={handleSend} className="flex flex-col gap-3 rounded-card border border-border bg-surface p-4">
            <TextareaField
              label="Ask your coach"
              value={userInput}
              onChange={(event) => setUserInput(event.target.value)}
              rows={3}
              disabled={isStreaming}
            />
            <Button type="submit" isLoading={isStreaming} disabled={!userInput.trim()} className="self-start">
              Send
            </Button>
          </form>
        ) : (
          <p className="text-sm text-muted">This conversation is closed.</p>
        )}
      </div>
    </div>
  );
}

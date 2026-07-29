"use client";

import { use, useState } from "react";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { ErrorState } from "@/components/ui/ErrorState";
import { PageHeading } from "@/components/ui/PageHeading";
import { LoadingSkeletonCard } from "@/components/ui/Skeleton";
import { TextareaField } from "@/components/ui/Textarea";
import { CoachTurnView } from "@/components/coach/CoachTurnView";
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
          <CoachTurnView
            key={turn.id}
            turn={turn}
            isStreaming={isStreaming}
            onApprove={() => void resumeTurn(turn.id, "APPROVE")}
            onReject={() => void resumeTurn(turn.id, "REJECT")}
          />
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

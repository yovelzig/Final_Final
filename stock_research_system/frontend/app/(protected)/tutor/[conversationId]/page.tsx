"use client";

import { use, useState } from "react";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { ErrorState } from "@/components/ui/ErrorState";
import { PageHeading } from "@/components/ui/PageHeading";
import { LoadingSkeletonCard } from "@/components/ui/Skeleton";
import { TextareaField } from "@/components/ui/Textarea";
import { CitationList } from "@/components/tutor/CitationList";
import { ContextSafetyBanner } from "@/components/tutor/ContextSafetyBanner";
import { TUTOR_CONTEXT_LABELS } from "@/components/tutor/labels";
import { LessonMarkdown } from "@/components/learning/LessonMarkdown";
import { formatDateTime } from "@/lib/formatting";
import { useAskQuestion, useCloseConversation, useConversation, useMessages } from "@/hooks/useTutor";
import type { AskResponse } from "@/types/api-schemas";

export default function TutorConversationPage({ params }: { params: Promise<{ conversationId: string }> }) {
  const { conversationId } = use(params);
  const conversationQuery = useConversation(conversationId);
  const messagesQuery = useMessages(conversationId);
  const askQuestion = useAskQuestion(conversationId);
  const closeConversation = useCloseConversation();

  const [question, setQuestion] = useState("");
  const [latestAnswer, setLatestAnswer] = useState<AskResponse | null>(null);

  if (conversationQuery.isPending || messagesQuery.isPending) {
    return <LoadingSkeletonCard />;
  }
  if (conversationQuery.isError) {
    return <ErrorState error={conversationQuery.error} onRetry={() => void conversationQuery.refetch()} />;
  }
  if (messagesQuery.isError) {
    return <ErrorState error={messagesQuery.error} onRetry={() => void messagesQuery.refetch()} />;
  }

  const conversation = conversationQuery.data;
  const isClosed = conversation.status !== "ACTIVE";

  const handleAsk = (event: React.FormEvent) => {
    event.preventDefault();
    if (!question.trim() || isClosed) return;
    askQuestion.mutate(
      { question: question.trim(), exercise_submitted: false, top_k: 8 },
      {
        onSuccess: (data) => {
          setLatestAnswer(data);
          setQuestion("");
        },
      }
    );
  };

  return (
    <div>
      <PageHeading
        title={TUTOR_CONTEXT_LABELS[conversation.context_type]}
        action={
          !isClosed ? (
            <Button variant="ghost" onClick={() => closeConversation.mutate(conversationId)} isLoading={closeConversation.isPending}>
              Close conversation
            </Button>
          ) : (
            <Badge tone="neutral">Closed</Badge>
          )
        }
      />

      <ContextSafetyBanner contextType={conversation.context_type} />

      <div className="mt-4 flex flex-col gap-4">
        <ul className="flex flex-col gap-3" aria-live="polite">
          {messagesQuery.data.map((message) => (
            <li
              key={message.message_id}
              className={`max-w-2xl rounded-card border p-4 text-sm ${
                message.role === "USER" ? "ml-auto border-primary/20 bg-primary-light" : "border-border bg-surface"
              }`}
            >
              <p className="mb-1 text-xs font-medium text-muted">
                {message.role === "USER" ? "You" : "Tutor"} · {formatDateTime(message.created_at)}
              </p>
              {message.role === "ASSISTANT" ? <LessonMarkdown content={message.content} /> : <p className="text-slate-800">{message.content}</p>}
            </li>
          ))}
        </ul>

        {latestAnswer && latestAnswer.citations.length > 0 ? <CitationList citations={latestAnswer.citations} /> : null}

        {askQuestion.isError ? <ErrorState error={askQuestion.error} /> : null}

        {!isClosed ? (
          <form onSubmit={handleAsk} className="flex flex-col gap-3 rounded-card border border-border bg-surface p-4">
            <TextareaField
              label="Ask a question"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              rows={3}
              disabled={askQuestion.isPending}
            />
            <Button type="submit" isLoading={askQuestion.isPending} disabled={!question.trim()} className="self-start">
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

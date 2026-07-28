"use client";

import { use, useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { ErrorState } from "@/components/ui/ErrorState";
import { PageHeading } from "@/components/ui/PageHeading";
import { LoadingSkeletonCard } from "@/components/ui/Skeleton";
import { TextareaField } from "@/components/ui/Textarea";
import { CitationList } from "@/components/tutor/CitationList";
import { ContextSafetyBanner } from "@/components/tutor/ContextSafetyBanner";
import { getTutorContextLabel } from "@/components/tutor/labels";
import { LessonMarkdown } from "@/components/learning/LessonMarkdown";
import { detectTextDirection } from "@/lib/i18n/config";
import { formatDateTime } from "@/lib/formatting";
import { useAskQuestion, useCloseConversation, useConversation, useMessages } from "@/hooks/useTutor";
import { useDictionary, useLocale } from "@/providers/LocaleProvider";
import type { AskQuestionRequest, AskResponse } from "@/types/api-schemas";

export default function TutorConversationPage({ params }: { params: Promise<{ conversationId: string }> }) {
  const { conversationId } = use(params);
  const t = useDictionary();
  const { locale } = useLocale();
  const conversationQuery = useConversation(conversationId);
  const messagesQuery = useMessages(conversationId);
  const askQuestion = useAskQuestion(conversationId);
  const closeConversation = useCloseConversation();

  const [question, setQuestion] = useState("");
  const [pendingQuestion, setPendingQuestion] = useState<AskQuestionRequest | null>(null);
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

  const submit = (body: AskQuestionRequest) => {
    setPendingQuestion(body);
    askQuestion.mutate(body, {
      onSuccess: (data) => {
        setLatestAnswer(data);
        setQuestion("");
      },
    });
  };

  const handleAsk = (event: React.FormEvent) => {
    event.preventDefault();
    const trimmed = question.trim();
    if (!trimmed || isClosed) return;
    // `trimmed` only strips leading/trailing whitespace - the Unicode
    // question text itself (Hebrew, English, or mixed) reaches the API
    // completely unchanged, never transliterated.
    submit({ question: trimmed, exercise_submitted: false, top_k: 8 });
  };

  const handleRetry = () => {
    if (pendingQuestion) submit(pendingQuestion);
  };

  const isRefused = latestAnswer?.guardrail_action === "REFUSE";
  const isInsufficientEvidence = !isRefused && latestAnswer?.grounding_status === "INSUFFICIENT_EVIDENCE";

  return (
    <div>
      <PageHeading
        title={getTutorContextLabel(t, conversation.context_type)}
        action={
          !isClosed ? (
            <Button variant="ghost" onClick={() => closeConversation.mutate(conversationId)} isLoading={closeConversation.isPending}>
              {t.tutor.closeConversation}
            </Button>
          ) : (
            <Badge tone="neutral">{t.tutor.closed}</Badge>
          )
        }
      />

      <ContextSafetyBanner contextType={conversation.context_type} />

      <div className="mt-4 flex flex-col gap-4">
        <ul className="flex flex-col gap-3" aria-live="polite">
          {messagesQuery.data.map((message) => {
            const isUser = message.role === "USER";
            return (
              <li
                key={message.message_id}
                dir={isUser ? detectTextDirection(message.content) : undefined}
                className={`max-w-2xl rounded-card border p-4 text-sm ${
                  isUser ? "ms-auto border-primary/20 bg-primary-light" : "border-border bg-surface"
                }`}
              >
                <p className="mb-1 text-xs font-medium text-muted">
                  {isUser ? t.tutor.you : t.tutor.tutorRole} · {formatDateTime(message.created_at, locale)}
                </p>
                {message.role === "ASSISTANT" ? (
                  <LessonMarkdown content={message.content} />
                ) : (
                  <p className="text-slate-800">{message.content}</p>
                )}
              </li>
            );
          })}
        </ul>

        {isRefused ? (
          <Alert tone="warning" title={t.tutor.refused.title}>
            {t.tutor.refused.description}
          </Alert>
        ) : isInsufficientEvidence ? (
          <Alert tone="warning" title={t.tutor.insufficientEvidence.title}>
            {t.tutor.insufficientEvidence.description}
          </Alert>
        ) : latestAnswer && latestAnswer.citations.length > 0 ? (
          <CitationList citations={latestAnswer.citations} />
        ) : null}

        {askQuestion.isError ? <ErrorState error={askQuestion.error} onRetry={handleRetry} /> : null}

        {!isClosed ? (
          <form onSubmit={handleAsk} className="flex flex-col gap-3 rounded-card border border-border bg-surface p-4">
            <TextareaField
              label={t.tutor.askLabel}
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              dir={detectTextDirection(question)}
              rows={3}
              disabled={askQuestion.isPending}
            />
            <Button type="submit" isLoading={askQuestion.isPending} disabled={!question.trim()} className="self-start">
              {t.tutor.send}
            </Button>
          </form>
        ) : (
          <p className="text-sm text-muted">{t.tutor.conversationClosedNotice}</p>
        )}
      </div>
    </div>
  );
}

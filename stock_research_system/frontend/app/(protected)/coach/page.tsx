"use client";

import { useRouter } from "next/navigation";
import Link from "next/link";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { PageHeading } from "@/components/ui/PageHeading";
import { LoadingSkeletonCard } from "@/components/ui/Skeleton";
import { formatRelativeTime } from "@/lib/formatting";
import { useCoachThreads, useCreateCoachThread } from "@/hooks/useLearningCoach";
import { useDictionary, useLocale } from "@/providers/LocaleProvider";

export default function CoachLandingPage() {
  const router = useRouter();
  const t = useDictionary();
  const { locale } = useLocale();
  const threadsQuery = useCoachThreads();
  const createThread = useCreateCoachThread();

  const handleStart = (title?: string) => {
    createThread.mutate(
      { title: title ?? t.coach.newConversation, initial_context_type: "GENERAL_EDUCATION" },
      { onSuccess: (thread) => router.push(`/coach/${thread.thread_id}`) }
    );
  };

  return (
    <div>
      <PageHeading
        title={t.coach.pageTitle}
        description={t.coach.description}
        action={
          <Button onClick={() => handleStart()} isLoading={createThread.isPending}>
            {t.coach.newConversation}
          </Button>
        }
      />

      {createThread.isError ? <ErrorState error={createThread.error} /> : null}

      <div className="mb-6 flex flex-wrap gap-2">
        {t.coach.suggestedPrompts.map((prompt) => (
          <button
            key={prompt}
            type="button"
            onClick={() => handleStart(prompt)}
            className="rounded-full border border-border bg-surface px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus-ring"
          >
            {prompt}
          </button>
        ))}
      </div>

      {threadsQuery.isPending ? (
        <LoadingSkeletonCard />
      ) : threadsQuery.isError ? (
        <ErrorState error={threadsQuery.error} onRetry={() => void threadsQuery.refetch()} />
      ) : threadsQuery.data.items.length === 0 ? (
        <EmptyState title={t.coach.emptyTitle} description={t.coach.emptyDescription} />
      ) : (
        <ul className="flex flex-col divide-y divide-border rounded-card border border-border bg-surface px-6">
          {threadsQuery.data.items.map((thread) => (
            <li key={thread.thread_id} className="py-3">
              <Link
                href={`/coach/${thread.thread_id}`}
                className="flex items-center justify-between gap-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus-ring"
              >
                <div>
                  <p className="text-sm font-medium text-slate-900">{thread.title}</p>
                  <p className="text-xs text-muted">{formatRelativeTime(thread.updated_at, new Date(), locale)}</p>
                </div>
                <Badge tone={thread.status === "ACTIVE" ? "success" : "neutral"}>{t.common.status[thread.status]}</Badge>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

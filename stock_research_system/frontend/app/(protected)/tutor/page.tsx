"use client";

import { useRouter } from "next/navigation";
import Link from "next/link";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { PageHeading } from "@/components/ui/PageHeading";
import { LoadingSkeletonCard } from "@/components/ui/Skeleton";
import { TUTOR_CONTEXT_LABELS } from "@/components/tutor/labels";
import { formatRelativeTime } from "@/lib/formatting";
import { useConversations, useCreateConversation } from "@/hooks/useTutor";

export default function TutorPage() {
  const router = useRouter();
  const conversationsQuery = useConversations();
  const createConversation = useCreateConversation();

  const handleStartGeneral = () => {
    createConversation.mutate(
      { context_type: "GENERAL_EDUCATION" },
      { onSuccess: (conversation) => router.push(`/tutor/${conversation.conversation_id}`) }
    );
  };

  return (
    <div>
      <PageHeading
        title="AI tutor"
        description="Ask questions grounded in FinQuest's curriculum. The tutor never gives personalized investment advice."
        action={
          <Button onClick={handleStartGeneral} isLoading={createConversation.isPending}>
            Ask a question
          </Button>
        }
      />

      {createConversation.isError ? <ErrorState error={createConversation.error} /> : null}

      {conversationsQuery.isPending ? (
        <LoadingSkeletonCard />
      ) : conversationsQuery.isError ? (
        <ErrorState error={conversationsQuery.error} onRetry={() => void conversationsQuery.refetch()} />
      ) : conversationsQuery.data.length === 0 ? (
        <EmptyState title="No conversations yet" description="Ask the tutor a question to get started." />
      ) : (
        <ul className="flex flex-col divide-y divide-border rounded-card border border-border bg-surface px-6">
          {conversationsQuery.data.map((conversation) => (
            <li key={conversation.conversation_id} className="py-3">
              <Link
                href={`/tutor/${conversation.conversation_id}`}
                className="flex items-center justify-between gap-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus-ring"
              >
                <div>
                  <p className="text-sm font-medium text-slate-900">{TUTOR_CONTEXT_LABELS[conversation.context_type]}</p>
                  <p className="text-xs text-muted">{formatRelativeTime(conversation.created_at)}</p>
                </div>
                <Badge tone={conversation.status === "ACTIVE" ? "success" : "neutral"}>{conversation.status}</Badge>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

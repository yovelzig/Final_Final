"use client";

import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/Button";
import { useCreateConversation } from "@/hooks/useTutor";
import type { CreateConversationRequest } from "@/types/api-schemas";

/** Starts (or would start) a context-scoped tutor conversation and
 * navigates to it - the backend decides what context/grounding is
 * actually available for the given ids, this only triggers creation. */
export function AskTutorButton({
  request,
  label = "Ask the tutor",
}: {
  request: CreateConversationRequest;
  label?: string;
}) {
  const router = useRouter();
  const createConversation = useCreateConversation();

  return (
    <Button
      variant="ghost"
      size="sm"
      isLoading={createConversation.isPending}
      onClick={() =>
        createConversation.mutate(request, {
          onSuccess: (conversation) => router.push(`/tutor/${conversation.conversation_id}`),
        })
      }
    >
      {label}
    </Button>
  );
}

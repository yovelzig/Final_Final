"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import type {
  AskQuestionRequest,
  AskResponse,
  CreateConversationRequest,
  TutorConversationResponse,
  TutorMessageResponse,
} from "@/types/api-schemas";

export function useConversations() {
  return useQuery({
    queryKey: queryKeys.tutor.conversations(),
    queryFn: () => apiClient.get<TutorConversationResponse[]>("/api/v1/tutor/conversations"),
  });
}

export function useConversation(conversationId: string) {
  return useQuery({
    queryKey: queryKeys.tutor.conversation(conversationId),
    queryFn: () => apiClient.get<TutorConversationResponse>(`/api/v1/tutor/conversations/${conversationId}`),
    enabled: !!conversationId,
  });
}

export function useCreateConversation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: CreateConversationRequest) =>
      apiClient.post<TutorConversationResponse>("/api/v1/tutor/conversations", body),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: queryKeys.tutor.conversations() }),
  });
}

export function useMessages(conversationId: string) {
  return useQuery({
    queryKey: queryKeys.tutor.messages(conversationId),
    queryFn: () => apiClient.get<TutorMessageResponse[]>(`/api/v1/tutor/conversations/${conversationId}/messages`),
    enabled: !!conversationId,
  });
}

export function useAskQuestion(conversationId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: AskQuestionRequest) =>
      apiClient.post<AskResponse>(`/api/v1/tutor/conversations/${conversationId}/messages`, body),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: queryKeys.tutor.messages(conversationId) }),
  });
}

export function useCloseConversation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (conversationId: string) =>
      apiClient.post<TutorConversationResponse>(`/api/v1/tutor/conversations/${conversationId}/close`),
    onSuccess: (_data, conversationId) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.tutor.conversations() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.tutor.conversation(conversationId) });
    },
  });
}

"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import type {
  CreateThreadRequest,
  LearningCoachApprovalRequest,
  LearningCoachEventResponse,
  LearningCoachRunResponse,
  LearningCoachThreadListResponse,
  LearningCoachThreadResponse,
  StartRunRequest,
} from "@/types/api-schemas";

export function useCoachThreads() {
  return useQuery({
    queryKey: queryKeys.coach.threads(),
    queryFn: () => apiClient.get<LearningCoachThreadListResponse>("/api/v1/coach/threads"),
  });
}

export function useCoachThread(threadId: string) {
  return useQuery({
    queryKey: queryKeys.coach.thread(threadId),
    queryFn: () => apiClient.get<LearningCoachThreadResponse>(`/api/v1/coach/threads/${threadId}`),
    enabled: !!threadId,
  });
}

export function useCreateCoachThread() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: CreateThreadRequest) => apiClient.post<LearningCoachThreadResponse>("/api/v1/coach/threads", body),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: queryKeys.coach.threads() }),
  });
}

export function useCloseCoachThread() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (threadId: string) =>
      apiClient.post<LearningCoachThreadResponse>(`/api/v1/coach/threads/${threadId}/close`),
    onSuccess: (_data, threadId) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.coach.threads() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.coach.thread(threadId) });
    },
  });
}

export function useCoachRun(runId: string | null) {
  return useQuery({
    queryKey: queryKeys.coach.run(runId ?? ""),
    queryFn: () => apiClient.get<LearningCoachRunResponse>(`/api/v1/coach/runs/${runId}`),
    enabled: !!runId,
  });
}

export function useCoachRunEvents(runId: string | null) {
  return useQuery({
    queryKey: queryKeys.coach.runEvents(runId ?? ""),
    queryFn: () => apiClient.get<LearningCoachEventResponse[]>(`/api/v1/coach/runs/${runId}/events`),
    enabled: !!runId,
  });
}

export function useStartCoachRun(threadId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ body, idempotencyKey }: { body: StartRunRequest; idempotencyKey: string }) =>
      apiClient.post<LearningCoachRunResponse>(`/api/v1/coach/threads/${threadId}/runs`, body, {
        headers: { "Idempotency-Key": idempotencyKey },
      }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: queryKeys.coach.thread(threadId) }),
  });
}

export function useResumeCoachRun(runId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: LearningCoachApprovalRequest) =>
      apiClient.post<LearningCoachRunResponse>(`/api/v1/coach/runs/${runId}/resume`, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.coach.run(runId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.coach.runEvents(runId) });
    },
  });
}

export function useCancelCoachRun() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (runId: string) => apiClient.post<LearningCoachRunResponse>(`/api/v1/coach/runs/${runId}/cancel`),
    onSuccess: (_data, runId) => void queryClient.invalidateQueries({ queryKey: queryKeys.coach.run(runId) }),
  });
}

export function generateIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `coach-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

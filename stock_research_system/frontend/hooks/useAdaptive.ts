"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import type {
  AdaptiveDecisionResponse,
  AttemptResponse,
  ExerciseRecommendationResponse,
  LearningSessionResponse,
  SessionSummaryResponse,
  StartRecommendedExerciseRequest,
  StartSessionRequest,
  SubmitDecisionAnswerRequest,
} from "@/types/api-schemas";

/** Every mutation below is a thin pass-through to one adaptive-learning
 * endpoint - priority, difficulty, and review-interval decisions are
 * always made by the backend policy, never recomputed here. */

export function useStartSession() {
  return useMutation({
    mutationFn: (body: StartSessionRequest) =>
      apiClient.post<LearningSessionResponse>("/api/v1/adaptive/sessions", body),
  });
}

export function useSession(sessionId: string | null) {
  return useQuery({
    queryKey: queryKeys.adaptive.session(sessionId ?? ""),
    queryFn: () => apiClient.get<LearningSessionResponse>(`/api/v1/adaptive/sessions/${sessionId}`),
    enabled: !!sessionId,
  });
}

export function useNextRecommendation() {
  return useMutation({
    mutationFn: (sessionId: string) =>
      apiClient.post<ExerciseRecommendationResponse>(`/api/v1/adaptive/sessions/${sessionId}/next`),
  });
}

export function useCompleteSession() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (sessionId: string) =>
      apiClient.post<SessionSummaryResponse>(`/api/v1/adaptive/sessions/${sessionId}/complete`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.learner.dashboard() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.learner.mastery() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.learner.progress() });
    },
  });
}

export function useAcceptDecision() {
  return useMutation({
    mutationFn: (decisionId: string) =>
      apiClient.post<AdaptiveDecisionResponse>(`/api/v1/adaptive/decisions/${decisionId}/accept`),
  });
}

export function useSkipDecision() {
  return useMutation({
    mutationFn: (decisionId: string) =>
      apiClient.post<AdaptiveDecisionResponse>(`/api/v1/adaptive/decisions/${decisionId}/skip`),
  });
}

export function useStartDecisionExercise() {
  return useMutation({
    mutationFn: ({ decisionId, body }: { decisionId: string; body: StartRecommendedExerciseRequest }) =>
      apiClient.post<AttemptResponse>(`/api/v1/adaptive/decisions/${decisionId}/start`, body),
  });
}

export function useSubmitDecisionAnswer() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ decisionId, body }: { decisionId: string; body: SubmitDecisionAnswerRequest }) =>
      apiClient.post<SessionSummaryResponse>(`/api/v1/adaptive/decisions/${decisionId}/answers`, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.learner.dashboard() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.learner.mastery() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.learner.progress() });
    },
  });
}

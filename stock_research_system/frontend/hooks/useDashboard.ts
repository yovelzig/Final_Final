"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import type {
  LearnerProfileResponse,
  LearnerUpdateRequest,
  PaginatedMisconceptionResponse,
  PaginatedProgressResponse,
  PaginatedSkillMasteryResponse,
} from "@/types/api-schemas";
import type { DashboardResponse } from "@/types/api-schemas";

export function useDashboard() {
  return useQuery({
    queryKey: queryKeys.learner.dashboard(),
    queryFn: () => apiClient.get<DashboardResponse>("/api/v1/learners/me/dashboard"),
  });
}

export function useMastery() {
  return useQuery({
    queryKey: queryKeys.learner.mastery(),
    queryFn: () => apiClient.get<PaginatedSkillMasteryResponse>("/api/v1/learners/me/mastery", { query: { limit: 50 } }),
  });
}

export function useProgress() {
  return useQuery({
    queryKey: queryKeys.learner.progress(),
    queryFn: () => apiClient.get<PaginatedProgressResponse>("/api/v1/learners/me/progress", { query: { limit: 50 } }),
  });
}

export function useMisconceptions() {
  return useQuery({
    queryKey: queryKeys.learner.misconceptions(),
    queryFn: () =>
      apiClient.get<PaginatedMisconceptionResponse>("/api/v1/learners/me/misconceptions", { query: { limit: 20 } }),
  });
}

/** Only display name, preferred language, and daily goal can ever be
 * changed here - the backend's `LearnerUpdateRequest` structurally
 * excludes role/status, so there is nothing else this could send. */
export function useUpdateLearner() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: LearnerUpdateRequest) => apiClient.patch<LearnerProfileResponse>("/api/v1/learners/me", body),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: queryKeys.learner.dashboard() }),
  });
}

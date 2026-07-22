"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import type {
  LearnerScenarioResponse,
  ScenarioCatalogItemResponse,
  ScenarioRevealResponse,
  ScenarioSubmissionResponse,
  SubmitDecisionRequest,
} from "@/types/api-schemas";
import type { components } from "@/types/generated-api";

type MarketScenarioType = components["schemas"]["MarketScenarioType"];

export function useScenarioCatalog(filters?: { skillId?: string; scenarioType?: MarketScenarioType }) {
  return useQuery({
    queryKey: [...queryKeys.scenarios.list(), filters ?? {}],
    queryFn: () =>
      apiClient.get<ScenarioCatalogItemResponse[]>("/api/v1/scenarios", {
        query: { skill_id: filters?.skillId, scenario_type: filters?.scenarioType },
      }),
  });
}

export function useScenario(scenarioId: string) {
  return useQuery({
    queryKey: queryKeys.scenarios.detail(scenarioId),
    queryFn: () => apiClient.get<LearnerScenarioResponse>(`/api/v1/scenarios/${scenarioId}`),
    enabled: !!scenarioId,
  });
}

export function useStartScenario() {
  return useMutation({
    mutationFn: (scenarioId: string) =>
      apiClient.post<ScenarioSubmissionResponse>(`/api/v1/scenarios/${scenarioId}/start`),
  });
}

export function useSubmitScenarioDecision() {
  return useMutation({
    mutationFn: ({ submissionId, body }: { submissionId: string; body: SubmitDecisionRequest }) =>
      apiClient.post<ScenarioSubmissionResponse>(`/api/v1/scenarios/submissions/${submissionId}/submit`, body),
  });
}

/** Only ever call this after the learner has explicitly chosen to see
 * the outcome - it returns future price data that must never be
 * fetched or rendered ahead of that action. */
export function useRevealScenario() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (submissionId: string) =>
      apiClient.post<ScenarioRevealResponse>(`/api/v1/scenarios/submissions/${submissionId}/reveal`),
    onSuccess: (data, submissionId) => {
      queryClient.setQueryData(queryKeys.scenarios.reveal(submissionId), data);
    },
  });
}

/** Re-fetches an already-revealed outcome (e.g. after a page reload).
 * Only enable this once the submission's own `reveal_status` is
 * already `REVEALED` - never speculatively. */
export function useExistingScenarioReveal(submissionId: string | null, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.scenarios.reveal(submissionId ?? ""),
    queryFn: () => apiClient.get<ScenarioRevealResponse>(`/api/v1/scenarios/submissions/${submissionId}/reveal`),
    enabled: !!submissionId && enabled,
  });
}

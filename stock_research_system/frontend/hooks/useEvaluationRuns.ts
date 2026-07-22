"use client";

import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import type {
  EvaluationRegressionReportResponse,
  QualityEvaluationBaselineListResponse,
  QualityEvaluationRunListResponse,
  QualityEvaluationRunResponse,
  QualityEvaluationSampleResultListResponse,
  QualityEvaluationSuiteListResponse,
  QualityMetricResultListResponse,
} from "@/types/api-schemas";

/** Admin-only quality-evaluation reads (spec section 23's dashboard).
 * Suite import/run creation/baseline approval stay CLI/direct-API
 * actions this phase - see the README's Phase 13 section. */

export function useEvaluationSuites() {
  return useQuery({
    queryKey: queryKeys.evaluations.suites(),
    queryFn: () => apiClient.get<QualityEvaluationSuiteListResponse>("/api/v1/admin/evaluations/suites"),
  });
}

export function useEvaluationRuns() {
  return useQuery({
    queryKey: queryKeys.evaluations.runs(),
    queryFn: () => apiClient.get<QualityEvaluationRunListResponse>("/api/v1/admin/evaluations/runs"),
    refetchInterval: 10_000,
  });
}

export function useEvaluationRun(runId: string) {
  return useQuery({
    queryKey: queryKeys.evaluations.run(runId),
    queryFn: () => apiClient.get<QualityEvaluationRunResponse>(`/api/v1/admin/evaluations/runs/${runId}`),
    enabled: !!runId,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      const stillRunning = status === "CREATED" || status === "QUEUED" || status === "RUNNING";
      return stillRunning ? 5_000 : false;
    },
  });
}

export function useEvaluationRunSamples(runId: string) {
  return useQuery({
    queryKey: queryKeys.evaluations.runSamples(runId),
    queryFn: () =>
      apiClient.get<QualityEvaluationSampleResultListResponse>(`/api/v1/admin/evaluations/runs/${runId}/samples`),
    enabled: !!runId,
  });
}

export function useEvaluationRunMetrics(runId: string) {
  return useQuery({
    queryKey: queryKeys.evaluations.runMetrics(runId),
    queryFn: () => apiClient.get<QualityMetricResultListResponse>(`/api/v1/admin/evaluations/runs/${runId}/metrics`),
    enabled: !!runId,
  });
}

export function useEvaluationBaselines(suiteId: string | null) {
  return useQuery({
    queryKey: ["evaluations", "baselines", suiteId] as const,
    queryFn: () =>
      apiClient.get<QualityEvaluationBaselineListResponse>("/api/v1/admin/evaluations/baselines", {
        query: { suite_id: suiteId ?? undefined },
      }),
    enabled: !!suiteId,
  });
}

export function useCompareRunToBaseline(runId: string, baselineId: string | null) {
  return useQuery({
    queryKey: ["evaluations", "runs", runId, "compare", baselineId] as const,
    queryFn: () =>
      apiClient.post<EvaluationRegressionReportResponse>(`/api/v1/admin/evaluations/runs/${runId}/compare`, {
        baseline_id: baselineId,
      }),
    enabled: !!runId && !!baselineId,
  });
}

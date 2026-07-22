"use client";

import { useMutation, useQuery } from "@tanstack/react-query";

import { apiClient } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import type {
  AttemptResponse,
  DiagnosticStatusResponse,
  DiagnosticSummaryResponse,
  StartDiagnosticItemRequest,
  StartDiagnosticRequest,
  SubmitDiagnosticResultRequest,
} from "@/types/api-schemas";

/** Every mutation is a thin pass-through to one diagnostic endpoint -
 * skill readiness and item selection are always decided by the
 * backend, never recomputed here. */

export function useStartDiagnostic() {
  return useMutation({
    mutationFn: (body: StartDiagnosticRequest) =>
      apiClient.post<DiagnosticSummaryResponse>("/api/v1/adaptive/diagnostics", body),
  });
}

export function useDiagnosticStatus(assessmentId: string | null) {
  return useQuery({
    queryKey: queryKeys.adaptive.diagnostic(assessmentId ?? ""),
    queryFn: () => apiClient.get<DiagnosticStatusResponse>(`/api/v1/adaptive/diagnostics/${assessmentId}`),
    enabled: !!assessmentId,
  });
}

export function useStartDiagnosticItem() {
  return useMutation({
    mutationFn: ({
      assessmentId,
      itemId,
      body,
    }: {
      assessmentId: string;
      itemId: string;
      body: StartDiagnosticItemRequest;
    }) =>
      apiClient.post<AttemptResponse>(
        `/api/v1/adaptive/diagnostics/${assessmentId}/items/${itemId}/start`,
        body
      ),
  });
}

export function useSubmitDiagnosticResult() {
  return useMutation({
    mutationFn: ({
      assessmentId,
      itemId,
      body,
    }: {
      assessmentId: string;
      itemId: string;
      body: SubmitDiagnosticResultRequest;
    }) =>
      apiClient.post<DiagnosticSummaryResponse>(
        `/api/v1/adaptive/diagnostics/${assessmentId}/items/${itemId}/result`,
        body
      ),
  });
}

export function useCompleteDiagnostic() {
  return useMutation({
    mutationFn: (assessmentId: string) =>
      apiClient.post<DiagnosticSummaryResponse>(`/api/v1/adaptive/diagnostics/${assessmentId}/complete`),
  });
}

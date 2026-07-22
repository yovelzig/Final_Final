"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import type {
  CreatePortfolioRequest,
  ExecuteTradeRequest,
  JournalEntryResponse,
  LatestValuationResponse,
  PerformanceSummaryResponse,
  PortfolioHoldingResponse,
  PortfolioOverviewResponse,
  PortfolioTransactionResponse,
  PortfolioValuationResultResponse,
  PreviewTradeRequest,
  RecordJournalEntryRequest,
  SecurityResponse,
  TradeExecutionResponse,
  TradePreviewResponse,
  ValueAsOfRequest,
  VirtualPortfolioResponse,
} from "@/types/api-schemas";

export function usePortfolios() {
  return useQuery({
    queryKey: queryKeys.portfolios.list(),
    queryFn: () => apiClient.get<VirtualPortfolioResponse[]>("/api/v1/portfolios"),
  });
}

export function useCreatePortfolio() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: CreatePortfolioRequest) => apiClient.post<VirtualPortfolioResponse>("/api/v1/portfolios", body),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: queryKeys.portfolios.list() }),
  });
}

export function usePortfolioOverview(portfolioId: string) {
  return useQuery({
    queryKey: queryKeys.portfolios.detail(portfolioId),
    queryFn: () => apiClient.get<PortfolioOverviewResponse>(`/api/v1/portfolios/${portfolioId}`),
    enabled: !!portfolioId,
  });
}

export function useSecurity(securityId: string | null) {
  return useQuery({
    queryKey: queryKeys.securities.detail(securityId ?? ""),
    queryFn: () => apiClient.get<SecurityResponse>(`/api/v1/portfolios/securities/${securityId}`),
    enabled: !!securityId,
    staleTime: 60 * 60 * 1000,
  });
}

export function usePreviewTrade(portfolioId: string) {
  return useMutation({
    mutationFn: (body: PreviewTradeRequest) =>
      apiClient.post<TradePreviewResponse>(`/api/v1/portfolios/${portfolioId}/trades/preview`, body),
  });
}

/** Requires the caller to pass a stable `idempotencyKey` from
 * `useIdempotencyKey` - retrying with the SAME key (e.g. after a
 * timeout) replays the original transaction instead of executing a
 * duplicate trade. */
export function useExecuteTrade(portfolioId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ body, idempotencyKey }: { body: ExecuteTradeRequest; idempotencyKey: string }) =>
      apiClient.post<TradeExecutionResponse>(`/api/v1/portfolios/${portfolioId}/trades`, body, {
        headers: { "Idempotency-Key": idempotencyKey },
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.portfolios.detail(portfolioId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.portfolios.transactions(portfolioId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.portfolios.holdings(portfolioId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.portfolios.journal(portfolioId) });
    },
  });
}

export function useTransactions(portfolioId: string) {
  return useQuery({
    queryKey: queryKeys.portfolios.transactions(portfolioId),
    queryFn: () => apiClient.get<PortfolioTransactionResponse[]>(`/api/v1/portfolios/${portfolioId}/transactions`),
    enabled: !!portfolioId,
  });
}

export function useHoldings(portfolioId: string) {
  return useQuery({
    queryKey: queryKeys.portfolios.holdings(portfolioId),
    queryFn: () => apiClient.get<PortfolioHoldingResponse[]>(`/api/v1/portfolios/${portfolioId}/holdings`),
    enabled: !!portfolioId,
  });
}

export function useJournalEntries(portfolioId: string) {
  return useQuery({
    queryKey: queryKeys.portfolios.journal(portfolioId),
    queryFn: () => apiClient.get<JournalEntryResponse[]>(`/api/v1/portfolios/${portfolioId}/journal`),
    enabled: !!portfolioId,
  });
}

export function useRecordJournalEntry(portfolioId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: RecordJournalEntryRequest) =>
      apiClient.post<JournalEntryResponse>(`/api/v1/portfolios/${portfolioId}/journal`, body),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: queryKeys.portfolios.journal(portfolioId) }),
  });
}

export function useLatestValuation(portfolioId: string) {
  return useQuery({
    queryKey: queryKeys.portfolios.latestValuation(portfolioId),
    queryFn: () => apiClient.get<LatestValuationResponse>(`/api/v1/portfolios/${portfolioId}/valuations/latest`),
    enabled: !!portfolioId,
  });
}

export function useValuePortfolio(portfolioId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ValueAsOfRequest) =>
      apiClient.post<PortfolioValuationResultResponse>(`/api/v1/portfolios/${portfolioId}/valuations`, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.portfolios.latestValuation(portfolioId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.portfolios.detail(portfolioId) });
    },
  });
}

export function usePerformance(portfolioId: string, startAt: string, endAt: string, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.portfolios.performance(portfolioId, startAt, endAt),
    queryFn: () =>
      apiClient.get<PerformanceSummaryResponse>(`/api/v1/portfolios/${portfolioId}/performance`, {
        query: { start_at: startAt, end_at: endAt },
      }),
    enabled: enabled && !!portfolioId,
  });
}

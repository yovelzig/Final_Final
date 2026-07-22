"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { FinQuestApiError } from "@/lib/api/client";

function shouldRetry(failureCount: number, error: unknown): boolean {
  if (error instanceof FinQuestApiError) {
    // Never retry a client error (4xx) - retrying an ownership/validation/
    // rate-limit failure just repeats the same failure. Only transient
    // 5xx/network conditions are worth a couple of retries.
    if (error.status >= 400 && error.status < 500) {
      return false;
    }
  }
  return failureCount < 2;
}

export function QueryProvider({ children }: { children: ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            retry: shouldRetry,
            staleTime: 30_000,
            refetchOnWindowFocus: false,
          },
          mutations: {
            retry: false,
          },
        },
      })
  );

  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

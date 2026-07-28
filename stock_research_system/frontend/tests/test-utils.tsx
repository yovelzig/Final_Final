import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, renderHook, type RenderHookOptions, type RenderOptions } from "@testing-library/react";
import type { ReactNode, ReactElement } from "react";

import type { Locale } from "@/lib/i18n/config";
import { AuthProvider } from "@/providers/AuthProvider";
import { LocaleProvider } from "@/providers/LocaleProvider";

function buildTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: 0, gcTime: 0 },
      mutations: { retry: false },
    },
  });
}

/** Renders a hook (e.g. a `useQuery`/`useMutation` wrapper from
 * `hooks/*`) inside a real `QueryClientProvider`, so it exercises the
 * actual TanStack Query + `apiClient` + `fetch` path against MSW -
 * the same integration boundary a page would use. */
export function renderHookWithQuery<TResult, TProps>(
  hook: (props: TProps) => TResult,
  options?: Omit<RenderHookOptions<TProps>, "wrapper">
) {
  const queryClient = buildTestQueryClient();
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  }
  return { queryClient, ...renderHook(hook, { wrapper: Wrapper, ...options }) };
}

/** Query-only wrapper - for components that don't touch auth state.
 * Still wrapped in `LocaleProvider` since shared primitives
 * (`ErrorState`, `LoadingSkeletonCard`, ...) read `useDictionary()`
 * unconditionally, matching the real `AppProviders` composition. */
export function renderWithQuery(
  ui: ReactElement,
  options?: Omit<RenderOptions, "wrapper"> & { locale?: Locale }
) {
  const queryClient = buildTestQueryClient();
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <LocaleProvider initialLocale={options?.locale ?? "en"}>
        <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
      </LocaleProvider>
    );
  }
  return { queryClient, ...render(ui, { wrapper: Wrapper, ...options }) };
}

/** Full provider stack, including `AuthProvider` - use for components
 * that read `useAuth()` or otherwise depend on session bootstrap.
 * Pass `{ locale: "he" }` to exercise Hebrew/RTL rendering. */
export function renderWithProviders(
  ui: ReactElement,
  options?: Omit<RenderOptions, "wrapper"> & { locale?: Locale }
) {
  const queryClient = buildTestQueryClient();
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <LocaleProvider initialLocale={options?.locale ?? "en"}>
        <QueryClientProvider client={queryClient}>
          <AuthProvider>{children}</AuthProvider>
        </QueryClientProvider>
      </LocaleProvider>
    );
  }
  return { queryClient, ...render(ui, { wrapper: Wrapper, ...options }) };
}

export * from "@testing-library/react";

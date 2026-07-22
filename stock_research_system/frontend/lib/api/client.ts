"use client";

import { browserEnv } from "@/lib/environment";
import { FinQuestApiError, parseApiError } from "@/lib/api/error";
import { getAccessTokenSnapshot, setAccessToken } from "@/lib/auth/token-store";

export type HttpMethod = "GET" | "POST" | "PATCH" | "PUT" | "DELETE";

export interface RequestOptions {
  method?: HttpMethod;
  body?: unknown;
  signal?: AbortSignal;
  /** Extra headers, e.g. `Idempotency-Key` for trade execution. Never
   * put a token or password in here directly - the client attaches the
   * bearer token itself. */
  headers?: Record<string, string>;
  /** Query string parameters, serialized with `URLSearchParams`
   * (booleans/numbers are stringified; `undefined`/`null` are omitted). */
  query?: Record<string, string | number | boolean | undefined | null>;
  /** Skip the automatic 401 -> refresh -> retry dance (used by the
   * refresh call itself, to avoid recursion). */
  skipAuthRetry?: boolean;
}

/** A single browser tab must never fire more than one concurrent
 * refresh request - every 401'd call awaits this SAME promise instead
 * of each starting its own rotation, since the backend's refresh-token
 * rotation treats a second concurrent rotation attempt as reuse and
 * revokes the whole session family. This is intentionally a plain
 * module-level variable (not part of React state) so it is shared
 * across every hook/component in the tab regardless of render timing. */
let inFlightRefresh: Promise<boolean> | null = null;

async function refreshOnce(): Promise<boolean> {
  if (inFlightRefresh) {
    return inFlightRefresh;
  }
  inFlightRefresh = (async () => {
    try {
      const response = await fetch("/api/auth/refresh", { method: "POST", credentials: "same-origin" });
      if (!response.ok) {
        setAccessToken(null);
        return false;
      }
      const body = (await response.json()) as
        | { authenticated: true; accessToken: string; accessTokenExpiresAt: string }
        | { authenticated: false };
      if (!body.authenticated) {
        setAccessToken(null);
        return false;
      }
      setAccessToken({ accessToken: body.accessToken, accessTokenExpiresAt: body.accessTokenExpiresAt });
      return true;
    } catch {
      setAccessToken(null);
      return false;
    }
  })();

  try {
    return await inFlightRefresh;
  } finally {
    inFlightRefresh = null;
  }
}

function buildUrl(path: string, query?: RequestOptions["query"]): string {
  const url = new URL(path, browserEnv.NEXT_PUBLIC_FINQUEST_API_BASE_URL);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== null) {
        url.searchParams.set(key, String(value));
      }
    }
  }
  return url.toString();
}

function generateCorrelationId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `client-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

async function performRequest<TResponse>(path: string, options: RequestOptions): Promise<TResponse> {
  const token = getAccessTokenSnapshot();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "X-Correlation-ID": generateCorrelationId(),
    ...options.headers,
  };
  if (token) {
    headers.Authorization = `Bearer ${token.accessToken}`;
  }

  const response = await fetch(buildUrl(path, options.query), {
    method: options.method ?? "GET",
    headers,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
    signal: options.signal,
  });

  if (response.ok) {
    if (response.status === 204) {
      return undefined as TResponse;
    }
    return (await response.json()) as TResponse;
  }

  if (response.status === 401 && !options.skipAuthRetry) {
    const refreshed = await refreshOnce();
    if (refreshed) {
      // Retry the ORIGINAL request at most once - never loop.
      return performRequest<TResponse>(path, { ...options, skipAuthRetry: true });
    }
  }

  throw await parseApiError(response);
}

/** The typed API client - all business (`/api/v1/*`) calls from Client
 * Components go through this, never a raw `fetch`. */
export const apiClient = {
  get<TResponse>(path: string, options?: Omit<RequestOptions, "method" | "body">): Promise<TResponse> {
    return performRequest<TResponse>(path, { ...options, method: "GET" });
  },
  post<TResponse>(path: string, body?: unknown, options?: Omit<RequestOptions, "method" | "body">): Promise<TResponse> {
    return performRequest<TResponse>(path, { ...options, method: "POST", body });
  },
  patch<TResponse>(path: string, body?: unknown, options?: Omit<RequestOptions, "method" | "body">): Promise<TResponse> {
    return performRequest<TResponse>(path, { ...options, method: "PATCH", body });
  },
  put<TResponse>(path: string, body?: unknown, options?: Omit<RequestOptions, "method" | "body">): Promise<TResponse> {
    return performRequest<TResponse>(path, { ...options, method: "PUT", body });
  },
};

export { FinQuestApiError };

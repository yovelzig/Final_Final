import { NextResponse } from "next/server";

import { apiInternalBaseUrl } from "@/lib/environment";
import { FinQuestApiError, parseApiError } from "@/lib/api/error";

/**
 * Server-only fetch helper used exclusively by the `/api/auth/*` Route
 * Handlers to call the real FastAPI backend - never used by
 * client-side code (see `lib/api/client.ts` for that). Always targets
 * `apiInternalBaseUrl()`, never the browser-facing public URL.
 */
export async function callBackend<TResponse>(
  path: string,
  init: { method: "GET" | "POST"; body?: unknown; accessToken?: string }
): Promise<TResponse> {
  const response = await fetch(`${apiInternalBaseUrl()}${path}`, {
    method: init.method,
    headers: {
      "Content-Type": "application/json",
      ...(init.accessToken ? { Authorization: `Bearer ${init.accessToken}` } : {}),
    },
    body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
    cache: "no-store",
  });

  if (!response.ok) {
    throw await parseApiError(response);
  }

  if (response.status === 204) {
    return undefined as TResponse;
  }
  return (await response.json()) as TResponse;
}

export { FinQuestApiError };

/** Renders a `FinQuestApiError` back into this frontend's own Route
 * Handler responses, using the same envelope shape the FastAPI backend
 * itself produces - so `lib/api/client.ts` (the browser-side client)
 * can parse an error from either origin identically. */
export function apiErrorResponse(error: FinQuestApiError): NextResponse {
  return NextResponse.json(
    {
      error: {
        code: error.code,
        message: error.message,
        details: error.details,
        correlation_id: error.correlationId,
      },
    },
    { status: error.status }
  );
}

export function invalidRequestBodyResponse(): NextResponse {
  return NextResponse.json(
    {
      error: {
        code: "INVALID_REQUEST_BODY",
        message: "Request body must be valid JSON.",
        details: [],
        correlation_id: null,
      },
    },
    { status: 400 }
  );
}

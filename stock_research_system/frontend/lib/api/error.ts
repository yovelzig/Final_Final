import { isApiErrorEnvelope, type ApiErrorDetail } from "@/types/api-error";

/**
 * Typed error raised by the API client for every non-2xx response.
 * Never carries the raw response body, request headers, or a stack
 * trace from the server - only the sanitized fields the backend's own
 * error envelope already promises to be safe.
 */
export class FinQuestApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: ApiErrorDetail[];
  readonly correlationId: string | null;

  constructor(params: {
    status: number;
    code: string;
    message: string;
    details?: ApiErrorDetail[];
    correlationId?: string | null;
  }) {
    super(params.message);
    this.name = "FinQuestApiError";
    this.status = params.status;
    this.code = params.code;
    this.details = params.details ?? [];
    this.correlationId = params.correlationId ?? null;
  }

  get isAuthenticationError(): boolean {
    return this.status === 401;
  }

  get isForbidden(): boolean {
    return this.status === 403;
  }

  get isNotFound(): boolean {
    return this.status === 404;
  }

  get isRateLimited(): boolean {
    return this.status === 429;
  }

  get isValidationError(): boolean {
    return this.status === 422;
  }
}

/** Parses a `Response` body into a `FinQuestApiError`, falling back to a
 * generic message if the body isn't the expected envelope shape (e.g. a
 * network intermediary or unrelated service returned something else). */
export async function parseApiError(response: Response): Promise<FinQuestApiError> {
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    // Non-JSON body (e.g. a proxy error page) - fall through to the generic case.
  }

  if (isApiErrorEnvelope(body)) {
    return new FinQuestApiError({
      status: response.status,
      code: body.error.code,
      message: body.error.message,
      details: body.error.details,
      correlationId: body.error.correlation_id,
    });
  }

  return new FinQuestApiError({
    status: response.status,
    code: "UNKNOWN_ERROR",
    message: `Request failed with status ${response.status}.`,
  });
}

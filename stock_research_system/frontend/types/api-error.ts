/**
 * The FastAPI backend's standard error envelope
 * (`api/schemas/common.py::ApiError`). Hand-written here because these
 * shapes are only ever produced by exception handlers - never used as
 * a route `response_model` - so they never appear in the generated
 * OpenAPI `components.schemas` and therefore never in
 * `types/generated-api.ts`.
 */
export interface ApiErrorDetail {
  field: string | null;
  message: string;
}

export interface ApiErrorBody {
  code: string;
  message: string;
  details: ApiErrorDetail[];
  correlation_id: string;
}

export interface ApiErrorEnvelope {
  error: ApiErrorBody;
}

export function isApiErrorEnvelope(value: unknown): value is ApiErrorEnvelope {
  if (typeof value !== "object" || value === null || !("error" in value)) {
    return false;
  }
  const error = (value as { error: unknown }).error;
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    "message" in error &&
    "correlation_id" in error
  );
}

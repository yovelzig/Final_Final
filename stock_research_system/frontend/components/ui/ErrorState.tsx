import { FinQuestApiError } from "@/lib/api/client";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";

/**
 * The single place that renders an API failure to a learner. Always
 * shows a calm, non-alarming message plus (only when present) a
 * correlation-id reference line for support - never a stack trace,
 * SQL, or raw error object.
 */
export function ErrorState({
  error,
  onRetry,
  title = "Something went wrong",
}: {
  error: unknown;
  onRetry?: () => void;
  title?: string;
}) {
  const message = friendlyMessage(error);
  const correlationId = error instanceof FinQuestApiError ? error.correlationId : null;

  return (
    <Alert tone="danger" title={title} role="alert">
      <p>{message}</p>
      {correlationId ? <p className="mt-2 text-xs opacity-75">Reference: {correlationId}</p> : null}
      {onRetry ? (
        <Button variant="ghost" size="sm" className="mt-3" onClick={onRetry}>
          Try again
        </Button>
      ) : null}
    </Alert>
  );
}

function friendlyMessage(error: unknown): string {
  if (error instanceof FinQuestApiError) {
    if (error.isRateLimited) return "You're doing that a bit too fast. Please wait a moment and try again.";
    if (error.isAuthenticationError) return "Your session has expired. Please sign in again.";
    if (error.isForbidden) return "You don't have permission to do that.";
    if (error.isNotFound) return "We couldn't find what you were looking for.";
    return error.message;
  }
  if (typeof navigator !== "undefined" && !navigator.onLine) {
    return "You appear to be offline. Check your connection and try again.";
  }
  return "An unexpected error occurred. Please try again.";
}

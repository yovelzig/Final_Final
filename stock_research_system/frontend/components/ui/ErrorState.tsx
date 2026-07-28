import { FinQuestApiError } from "@/lib/api/client";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { useDictionary } from "@/providers/LocaleProvider";
import type { Dictionary } from "@/lib/i18n/types";

/**
 * The single place that renders an API failure to a learner. Always
 * shows a calm, non-alarming message plus (only when present) a
 * correlation-id reference line for support - never a stack trace,
 * SQL, or raw error object. Bilingual by default since it reads the
 * active dictionary itself - callers never need to pass translated
 * copy in.
 */
export function ErrorState({
  error,
  onRetry,
  title,
}: {
  error: unknown;
  onRetry?: () => void;
  title?: string;
}) {
  const t = useDictionary();
  const message = friendlyMessage(error, t);
  const correlationId = error instanceof FinQuestApiError ? error.correlationId : null;

  return (
    <Alert tone="danger" title={title ?? t.common.somethingWentWrong} role="alert">
      <p>{message}</p>
      {correlationId ? (
        <p className="mt-2 text-xs opacity-75">
          {t.common.referenceLabel}: {correlationId}
        </p>
      ) : null}
      {onRetry ? (
        <Button variant="ghost" size="sm" className="mt-3" onClick={onRetry}>
          {t.common.retry}
        </Button>
      ) : null}
    </Alert>
  );
}

function friendlyMessage(error: unknown, t: Dictionary): string {
  if (error instanceof FinQuestApiError) {
    if (error.isRateLimited) return t.common.rateLimited;
    if (error.isAuthenticationError) return t.common.sessionExpired;
    if (error.isForbidden) return t.common.forbidden;
    if (error.isNotFound) return t.common.notFound;
    return error.message;
  }
  if (typeof navigator !== "undefined" && !navigator.onLine) {
    return t.common.offline;
  }
  return t.common.somethingWentWrong;
}

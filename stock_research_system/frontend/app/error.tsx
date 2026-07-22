"use client";

import { useEffect } from "react";

import { Button } from "@/components/ui/Button";

export default function GlobalError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    // Never log the error's raw message/stack to a third party here -
    // this is a client-side console log only, for local debugging.
    console.error(error);
  }, [error]);

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-background px-6 text-center">
      <h1 className="text-2xl font-bold text-slate-900">Something went wrong</h1>
      <p className="max-w-sm text-sm text-muted">
        An unexpected error occurred. You can try again, or go back to the dashboard.
      </p>
      {error.digest ? <p className="text-xs text-muted">Reference: {error.digest}</p> : null}
      <Button onClick={reset}>Try again</Button>
    </div>
  );
}

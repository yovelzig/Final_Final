"use client";

import { useEffect } from "react";

import { Button } from "@/components/ui/Button";
import { useDictionary } from "@/providers/LocaleProvider";

export default function GlobalError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  const t = useDictionary();

  useEffect(() => {
    // Never log the error's raw message/stack to a third party here -
    // this is a client-side console log only, for local debugging.
    console.error(error);
  }, [error]);

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-background px-6 text-center">
      <h1 className="text-2xl font-bold text-slate-900">{t.common.somethingWentWrong}</h1>
      <p className="max-w-sm text-sm text-muted">{t.common.globalErrorDescription}</p>
      {error.digest ? (
        <p className="text-xs text-muted">
          {t.common.referenceLabel}: {error.digest}
        </p>
      ) : null}
      <Button onClick={reset}>{t.common.retry}</Button>
    </div>
  );
}

"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect } from "react";

import { LanguageSwitcher } from "@/components/ui/LanguageSwitcher";
import { useAuth } from "@/hooks/useAuth";
import { useDictionary } from "@/providers/LocaleProvider";
import { sanitizeReturnPath } from "@/lib/auth/return-path";

/** Isolated so `useSearchParams()` doesn't force the whole auth layout
 * (and therefore /login and /register) to opt out of static rendering
 * - only this leaf needs a Suspense boundary. */
function AuthenticatedRedirect() {
  const { status } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();

  useEffect(() => {
    if (status === "authenticated") {
      router.replace(sanitizeReturnPath(searchParams.get("returnTo")));
    }
  }, [status, router, searchParams]);

  return null;
}

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  const t = useDictionary();
  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-background px-4 py-10">
      <Suspense fallback={null}>
        <AuthenticatedRedirect />
      </Suspense>
      <div className="mb-8 flex w-full max-w-md items-center justify-between">
        <span className="text-2xl font-bold text-primary">{t.common.finquest}</span>
        <LanguageSwitcher />
      </div>
      <div className="w-full max-w-md">{children}</div>
    </div>
  );
}

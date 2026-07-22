"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { AppShell } from "@/components/layout/AppShell";
import { LoadingSkeletonCard } from "@/components/ui/Skeleton";
import { useAuth } from "@/hooks/useAuth";

/**
 * The real client-side authorization boundary for the app's UI: this
 * (not `middleware.ts`, which only checks cookie *presence*) is what
 * actually verifies the session bootstrapped successfully before
 * rendering any learner data, and is what handles the case where the
 * refresh cookie exists but is no longer valid.
 */
export default function ProtectedLayout({ children }: { children: React.ReactNode }) {
  const { status } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (status === "unauthenticated") {
      router.replace("/login");
    }
  }, [status, router]);

  if (status === "loading") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background p-6">
        <div className="w-full max-w-sm">
          <LoadingSkeletonCard />
        </div>
      </div>
    );
  }

  if (status === "unauthenticated") {
    return null;
  }

  return <AppShell>{children}</AppShell>;
}

"use client";

import type { ReactNode } from "react";

import { AuthProvider } from "@/providers/AuthProvider";
import { QueryProvider } from "@/providers/QueryProvider";

/** Root provider composition - order matters: `AuthProvider` calls
 * `useQueryClient()` to clear the cache on logout, so it must be
 * nested inside `QueryProvider`. */
export function AppProviders({ children }: { children: ReactNode }) {
  return (
    <QueryProvider>
      <AuthProvider>{children}</AuthProvider>
    </QueryProvider>
  );
}

"use client";

import Link from "next/link";

import { useAuth } from "@/hooks/useAuth";

export function TopBar() {
  const { account } = useAuth();

  return (
    <header className="flex items-center justify-between border-b border-border bg-surface px-4 py-3 lg:hidden">
      <Link href="/dashboard" className="text-lg font-bold text-primary">
        FinQuest
      </Link>
      {account ? (
        <Link href="/settings" className="text-sm font-medium text-slate-600">
          {account.display_name}
        </Link>
      ) : null}
    </header>
  );
}

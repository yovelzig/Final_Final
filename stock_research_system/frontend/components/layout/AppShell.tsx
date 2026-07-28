"use client";

import type { ReactNode } from "react";

import { BottomNav } from "@/components/layout/BottomNav";
import { Sidebar } from "@/components/layout/Sidebar";
import { TopBar } from "@/components/layout/TopBar";
import { useDictionary } from "@/providers/LocaleProvider";

export function AppShell({ children }: { children: ReactNode }) {
  const t = useDictionary();
  return (
    <div className="flex min-h-screen flex-col lg:flex-row">
      <a
        href="#main-content"
        className="sr-only-focusable fixed start-2 top-2 z-50 rounded-md bg-primary px-3 py-2 text-sm text-white"
      >
        {t.nav.skipToContent}
      </a>
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar />
        <main id="main-content" className="min-w-0 flex-1 overflow-x-hidden px-4 py-6 pb-20 lg:px-8 lg:py-8 lg:pb-8">
          {children}
        </main>
      </div>
      <BottomNav />
    </div>
  );
}

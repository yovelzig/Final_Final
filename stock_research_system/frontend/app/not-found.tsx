"use client";

import Link from "next/link";

import { useDictionary } from "@/providers/LocaleProvider";

export default function NotFound() {
  const t = useDictionary();
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-background px-6 text-center">
      <h1 className="text-2xl font-bold text-slate-900">{t.common.pageNotFoundTitle}</h1>
      <p className="max-w-sm text-sm text-muted">{t.common.pageNotFoundDescription}</p>
      <Link href="/dashboard" className="rounded-lg bg-primary px-5 py-2.5 text-sm font-medium text-white hover:bg-primary-hover">
        {t.common.backToDashboard}
      </Link>
    </div>
  );
}

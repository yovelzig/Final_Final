import { useDictionary } from "@/providers/LocaleProvider";

export function Skeleton({ className = "" }: { className?: string }) {
  return <div aria-hidden="true" className={`animate-pulse rounded-md bg-slate-200 ${className}`} />;
}

export function LoadingSkeletonCard() {
  const t = useDictionary();
  return (
    <div className="rounded-card border border-border bg-surface p-5" role="status" aria-label={t.common.loading}>
      <span className="sr-only">{t.common.loading}</span>
      <Skeleton className="h-4 w-1/3" />
      <Skeleton className="mt-3 h-3 w-full" />
      <Skeleton className="mt-2 h-3 w-2/3" />
    </div>
  );
}

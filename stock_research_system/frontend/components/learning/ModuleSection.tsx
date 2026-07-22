"use client";

import Link from "next/link";

import { Badge } from "@/components/ui/Badge";
import { ErrorState } from "@/components/ui/ErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { useLessons } from "@/hooks/useCurriculum";
import { useProgress } from "@/hooks/useDashboard";
import type { LearningModuleResponse } from "@/types/api-schemas";

export function ModuleSection({ module }: { module: LearningModuleResponse }) {
  const lessonsQuery = useLessons(module.module_id);
  const progressQuery = useProgress();

  const progressByLessonId = new Map(
    (progressQuery.data?.items ?? []).filter((item) => item.lesson_id).map((item) => [item.lesson_id, item])
  );

  return (
    <section aria-labelledby={`module-${module.module_id}`} className="rounded-card border border-border bg-surface p-4">
      <h2 id={`module-${module.module_id}`} className="text-base font-semibold text-slate-900">
        {module.title}
      </h2>
      <p className="mt-1 text-sm text-muted">{module.description}</p>

      {lessonsQuery.isPending ? (
        <div className="mt-3 flex flex-col gap-2">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      ) : lessonsQuery.isError ? (
        <div className="mt-3">
          <ErrorState error={lessonsQuery.error} onRetry={() => void lessonsQuery.refetch()} />
        </div>
      ) : (
        <ol className="mt-3 flex flex-col gap-2">
          {lessonsQuery.data
            .slice()
            .sort((a, b) => a.position - b.position)
            .map((lesson) => {
              const progress = progressByLessonId.get(lesson.lesson_id);
              const isComplete = !!progress?.completed_at;
              return (
                <li key={lesson.lesson_id}>
                  <Link
                    href={`/lessons/${lesson.lesson_id}`}
                    className="flex items-center justify-between rounded-lg border border-border px-3 py-2.5 text-sm transition-colors hover:border-primary hover:bg-primary-light"
                  >
                    <span className="text-slate-800">{lesson.title}</span>
                    {isComplete ? <Badge tone="success">Completed</Badge> : <Badge tone="neutral">{lesson.estimated_minutes} min</Badge>}
                  </Link>
                </li>
              );
            })}
        </ol>
      )}
    </section>
  );
}

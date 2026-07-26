"use client";

import Link from "next/link";

import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { ErrorState } from "@/components/ui/ErrorState";
import { PageHeading } from "@/components/ui/PageHeading";
import { LoadingSkeletonCard } from "@/components/ui/Skeleton";
import { ExercisePlayer } from "@/components/exercises/ExercisePlayer";
import { LessonMarkdown } from "@/components/learning/LessonMarkdown";
import { AskTutorButton } from "@/components/tutor/AskTutorButton";
import { useLesson, useLessonExercises } from "@/hooks/useCurriculum";
import { useDashboard, useProgress } from "@/hooks/useDashboard";

export function LessonPageContent({ lessonId }: { lessonId: string }) {
  const lessonQuery = useLesson(lessonId);
  const exercisesQuery = useLessonExercises(lessonId);
  const dashboardQuery = useDashboard();
  const progressQuery = useProgress();

  if (lessonQuery.isPending) {
    return <LoadingSkeletonCard />;
  }
  if (lessonQuery.isError) {
    return <ErrorState error={lessonQuery.error} onRetry={() => void lessonQuery.refetch()} />;
  }

  const completionDataUnavailable =
    dashboardQuery.isPending ||
    dashboardQuery.isFetching ||
    dashboardQuery.isError ||
    progressQuery.isPending ||
    progressQuery.isFetching ||
    progressQuery.isError;

  const lessonProgress = progressQuery.data?.items.find((item) => item.lesson_id === lessonId);
  const isTerminalLesson = lessonProgress?.status === "COMPLETED" || lessonProgress?.status === "MASTERED";
  const currentLessonId = dashboardQuery.data?.current_lesson_id ?? null;

  return (
    <div>
      <PageHeading
        title={lessonQuery.data.title}
        description={lessonQuery.data.summary}
        action={<Badge tone="neutral">~{lessonQuery.data.estimated_minutes} min</Badge>}
      />

      <div className="rounded-card border border-border bg-surface p-5">
        <LessonMarkdown content={lessonQuery.data.content_markdown} />
        <div className="mt-4">
          <AskTutorButton
            request={{ context_type: "LESSON_HELP", lesson_id: lessonId }}
            label="Ask the tutor about this lesson"
          />
        </div>
      </div>

      {!completionDataUnavailable && isTerminalLesson ? (
        <div className="mt-6">
          {currentLessonId !== null && currentLessonId !== lessonId ? (
            <Alert tone="success" title="Lesson complete.">
              {/* Native anchor, not next/link: this CTA's client-side Link
               * transition was observed to repeatedly not update the
               * browser URL or rendered lesson, even though the href was
               * correct and direct navigation to it worked. The deeper
               * cause was not determined, so this one recovery-critical
               * CTA intentionally performs a full document navigation
               * instead. */}
              <a href={`/lessons/${currentLessonId}`} className="font-medium text-primary hover:underline">
                Continue learning
              </a>
            </Alert>
          ) : currentLessonId === null ? (
            <Alert tone="success" title="You're all caught up.">
              <p>Review the available learning paths to continue.</p>
              <Link href="/learn" className="font-medium text-primary hover:underline">
                Review learning paths
              </Link>
            </Alert>
          ) : (
            <Alert tone="success" title="Lesson complete.">
              <Link href="/learn" className="font-medium text-primary hover:underline">
                Review learning paths
              </Link>
            </Alert>
          )}
        </div>
      ) : null}

      <h2 className="mb-3 mt-8 text-lg font-semibold text-slate-900">Exercises</h2>
      {exercisesQuery.isPending ? (
        <LoadingSkeletonCard />
      ) : exercisesQuery.isError ? (
        <ErrorState error={exercisesQuery.error} onRetry={() => void exercisesQuery.refetch()} />
      ) : exercisesQuery.data.length === 0 ? (
        <p className="text-sm text-muted">This lesson has no exercises yet.</p>
      ) : (
        <div className="flex flex-col gap-4">
          {exercisesQuery.data
            .slice()
            .sort((a, b) => a.position - b.position)
            .map((exercise) => (
              <ExercisePlayer key={exercise.exercise_id} exercise={exercise} />
            ))}
        </div>
      )}
    </div>
  );
}

"use client";

import { use } from "react";

import { Badge } from "@/components/ui/Badge";
import { ErrorState } from "@/components/ui/ErrorState";
import { PageHeading } from "@/components/ui/PageHeading";
import { LoadingSkeletonCard } from "@/components/ui/Skeleton";
import { ExercisePlayer } from "@/components/exercises/ExercisePlayer";
import { LessonMarkdown } from "@/components/learning/LessonMarkdown";
import { AskTutorButton } from "@/components/tutor/AskTutorButton";
import { useLesson, useLessonExercises } from "@/hooks/useCurriculum";

export default function LessonPage({ params }: { params: Promise<{ lessonId: string }> }) {
  const { lessonId } = use(params);
  const lessonQuery = useLesson(lessonId);
  const exercisesQuery = useLessonExercises(lessonId);

  if (lessonQuery.isPending) {
    return <LoadingSkeletonCard />;
  }
  if (lessonQuery.isError) {
    return <ErrorState error={lessonQuery.error} onRetry={() => void lessonQuery.refetch()} />;
  }

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

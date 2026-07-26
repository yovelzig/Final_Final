"use client";

import { Badge } from "@/components/ui/Badge";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { PageHeading } from "@/components/ui/PageHeading";
import { LoadingSkeletonCard } from "@/components/ui/Skeleton";
import { ModuleSection } from "@/components/learning/ModuleSection";
import { useLearningPath, useModules } from "@/hooks/useCurriculum";

export function LearningPathPageContent({ pathId }: { pathId: string }) {
  const pathQuery = useLearningPath(pathId);
  const modulesQuery = useModules(pathId);

  if (pathQuery.isPending) {
    return <LoadingSkeletonCard />;
  }
  if (pathQuery.isError) {
    return <ErrorState error={pathQuery.error} onRetry={() => void pathQuery.refetch()} />;
  }

  return (
    <div>
      <PageHeading
        title={pathQuery.data.title}
        description={pathQuery.data.description}
        action={<Badge tone="neutral">{pathQuery.data.difficulty}</Badge>}
      />

      {modulesQuery.isPending ? (
        <LoadingSkeletonCard />
      ) : modulesQuery.isError ? (
        <ErrorState error={modulesQuery.error} onRetry={() => void modulesQuery.refetch()} />
      ) : modulesQuery.data.length === 0 ? (
        <EmptyState title="No modules are available in this learning path yet." />
      ) : (
        <div className="flex flex-col gap-4">
          {modulesQuery.data
            .slice()
            .sort((a, b) => a.position - b.position)
            .map((module) => (
              <ModuleSection key={module.module_id} module={module} />
            ))}
        </div>
      )}
    </div>
  );
}

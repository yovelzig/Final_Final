"use client";

import Link from "next/link";

import { Card, CardDescription, CardTitle } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { PageHeading } from "@/components/ui/PageHeading";
import { LoadingSkeletonCard } from "@/components/ui/Skeleton";
import { useLearningPaths } from "@/hooks/useCurriculum";

export default function LearnPage() {
  const pathsQuery = useLearningPaths();

  return (
    <div>
      <PageHeading title="Learn" description="Financial-literacy learning paths." />

      {pathsQuery.isPending ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <LoadingSkeletonCard />
          <LoadingSkeletonCard />
        </div>
      ) : pathsQuery.isError ? (
        <ErrorState error={pathsQuery.error} onRetry={() => void pathsQuery.refetch()} />
      ) : pathsQuery.data.length === 0 ? (
        <EmptyState title="No learning paths are available yet" />
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {pathsQuery.data
            .slice()
            .sort((a, b) => a.position - b.position)
            .map((path) => (
              <Link key={path.path_id} href={`/learn/${path.path_id}`}>
                <Card className="h-full transition-colors hover:border-primary">
                  <div className="mb-2 flex items-center justify-between">
                    <CardTitle>{path.title}</CardTitle>
                    <Badge tone="neutral">{path.difficulty}</Badge>
                  </div>
                  <CardDescription>{path.description}</CardDescription>
                  <p className="mt-3 text-xs text-muted">~{path.estimated_minutes} min</p>
                </Card>
              </Link>
            ))}
        </div>
      )}
    </div>
  );
}

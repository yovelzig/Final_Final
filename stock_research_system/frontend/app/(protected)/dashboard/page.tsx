"use client";

import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { PageHeading } from "@/components/ui/PageHeading";
import { LoadingSkeletonCard } from "@/components/ui/Skeleton";
import { MasteryList } from "@/components/dashboard/MasteryList";
import { QuickActions } from "@/components/dashboard/QuickActions";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { useAuth } from "@/hooks/useAuth";
import { useDashboard, useMastery } from "@/hooks/useDashboard";

export default function DashboardPage() {
  const { account } = useAuth();
  const dashboardQuery = useDashboard();
  const masteryQuery = useMastery();

  return (
    <div>
      <PageHeading
        title={account ? `Welcome back, ${account.display_name}` : "Dashboard"}
        description="Your learning at a glance."
      />

      <div className="mb-6">
        <QuickActions />
      </div>

      {dashboardQuery.isPending ? (
        <LoadingSkeletonCard />
      ) : dashboardQuery.isError ? (
        <ErrorState error={dashboardQuery.error} onRetry={() => void dashboardQuery.refetch()} />
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle>Progress</CardTitle>
              <CardDescription>Lessons completed on your current path.</CardDescription>
            </CardHeader>
            {dashboardQuery.data.total_lessons > 0 ? (
              <ProgressBar
                label="Lessons completed"
                value={dashboardQuery.data.completed_lessons}
                max={dashboardQuery.data.total_lessons}
              />
            ) : (
              <EmptyState
                title="You haven't started a learning path yet"
                description="Head to Learn to pick your first path."
              />
            )}
            {dashboardQuery.data.active_misconceptions.length > 0 ? (
              <div className="mt-4 rounded-lg bg-warning-light px-3 py-2 text-xs text-warning">
                {dashboardQuery.data.active_misconceptions.length} active misconception
                {dashboardQuery.data.active_misconceptions.length === 1 ? "" : "s"} to review.
              </div>
            ) : null}
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Skill mastery</CardTitle>
              <CardDescription>How you&apos;re doing across assessed skills.</CardDescription>
            </CardHeader>
            {masteryQuery.isPending ? (
              <LoadingSkeletonCard />
            ) : masteryQuery.isError ? (
              <ErrorState error={masteryQuery.error} onRetry={() => void masteryQuery.refetch()} />
            ) : (
              <MasteryList items={masteryQuery.data.items} />
            )}
          </Card>
        </div>
      )}
    </div>
  );
}

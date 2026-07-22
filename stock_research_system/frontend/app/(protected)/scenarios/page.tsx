"use client";

import Link from "next/link";

import { Badge } from "@/components/ui/Badge";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { PageHeading } from "@/components/ui/PageHeading";
import { LoadingSkeletonCard } from "@/components/ui/Skeleton";
import { useScenarioCatalog } from "@/hooks/useScenarios";

export default function ScenariosCatalogPage() {
  const scenariosQuery = useScenarioCatalog();

  return (
    <div>
      <PageHeading
        title="Historical scenarios"
        description="Practice real investment decisions using real historical market data - without knowing what happens next."
      />

      {scenariosQuery.isPending ? (
        <LoadingSkeletonCard />
      ) : scenariosQuery.isError ? (
        <ErrorState error={scenariosQuery.error} onRetry={() => void scenariosQuery.refetch()} />
      ) : scenariosQuery.data.length === 0 ? (
        <EmptyState title="No scenarios available yet" description="Check back soon for new historical scenarios." />
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {scenariosQuery.data.map((scenario) => (
            <Link
              key={scenario.scenario_id}
              href={`/scenarios/${scenario.scenario_id}`}
              className="rounded-card border border-border bg-surface p-5 transition-shadow hover:shadow-md focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus-ring"
            >
              <div className="mb-2 flex items-center gap-2">
                <Badge tone="primary">{scenario.scenario_type.replace(/_/g, " ")}</Badge>
                <Badge tone="neutral">{scenario.difficulty}</Badge>
              </div>
              <h2 className="text-base font-semibold text-slate-900">{scenario.title}</h2>
              <p className="mt-1 text-sm text-muted">{scenario.description}</p>
              <p className="mt-3 text-xs text-muted">~{scenario.estimated_minutes} min</p>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

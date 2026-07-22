"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { Badge, type BadgeTone } from "@/components/ui/Badge";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { PageHeading } from "@/components/ui/PageHeading";
import { LoadingSkeletonCard } from "@/components/ui/Skeleton";
import { useAuth } from "@/hooks/useAuth";
import { useEvaluationRuns, useEvaluationSuites } from "@/hooks/useEvaluationRuns";
import type { QualityEvaluationRunResponse, QualityEvaluationRunStatus } from "@/types/api-schemas";

const STATUS_TONE: Record<QualityEvaluationRunStatus, BadgeTone> = {
  CREATED: "neutral",
  QUEUED: "neutral",
  RUNNING: "primary",
  SUCCEEDED: "success",
  PARTIALLY_SUCCEEDED: "warning",
  FAILED: "danger",
  CANCELLED: "neutral",
};

/**
 * ADMIN-only quality-evaluation dashboard (spec section 23). The
 * backend's `require_admin` dependency is the real authorization
 * boundary - this client-side check only prevents a non-admin from
 * seeing the page flash before the API call fails; a direct-navigation
 * attempt from a non-admin still fails safely via `ErrorState`'s
 * `isForbidden` handling below if this check is ever bypassed.
 */
export default function EvaluationsDashboardPage() {
  const { account, status } = useAuth();
  const router = useRouter();
  const isAdmin = account?.role === "ADMIN";

  useEffect(() => {
    if (status === "authenticated" && !isAdmin) {
      router.replace("/dashboard");
    }
  }, [status, isAdmin, router]);

  const suitesQuery = useEvaluationSuites();
  const runsQuery = useEvaluationRuns();

  if (status !== "authenticated" || !isAdmin) {
    return <LoadingSkeletonCard />;
  }

  return (
    <div>
      <PageHeading
        title="Quality evaluations"
        description="Deterministic and RAGAS-based quality evaluation runs for the grounded tutor and learning Coach. Admin-only."
      />

      <section aria-labelledby="suites-heading" className="mb-8">
        <h2 id="suites-heading" className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted">
          Suites
        </h2>
        {suitesQuery.isPending ? (
          <LoadingSkeletonCard />
        ) : suitesQuery.isError ? (
          <ErrorState error={suitesQuery.error} onRetry={() => void suitesQuery.refetch()} />
        ) : suitesQuery.data.items.length === 0 ? (
          <EmptyState
            title="No suites imported yet"
            description="Import a curated suite with the quality_evaluation_admin CLI, then approve it before running an evaluation."
          />
        ) : (
          <div className="overflow-x-auto rounded-card border border-border bg-surface">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">Evaluation suites: code, type, version, status, and case count</caption>
              <thead className="border-b border-border text-xs uppercase text-muted">
                <tr>
                  <th scope="col" className="px-4 py-3">Code</th>
                  <th scope="col" className="px-4 py-3">Type</th>
                  <th scope="col" className="px-4 py-3">Version</th>
                  <th scope="col" className="px-4 py-3">Status</th>
                  <th scope="col" className="px-4 py-3">Cases</th>
                </tr>
              </thead>
              <tbody>
                {suitesQuery.data.items.map((suite) => (
                  <tr key={suite.suite_id} className="border-b border-border last:border-0">
                    <td className="px-4 py-3 font-medium text-slate-900">{suite.code}</td>
                    <td className="px-4 py-3 text-muted">{suite.suite_type}</td>
                    <td className="px-4 py-3 text-muted">{suite.version}</td>
                    <td className="px-4 py-3">
                      <Badge tone={suite.status === "APPROVED" ? "success" : "neutral"}>{suite.status}</Badge>
                    </td>
                    <td className="px-4 py-3 text-muted">{suite.case_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section aria-labelledby="runs-heading">
        <h2 id="runs-heading" className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted">
          Recent runs
        </h2>
        {runsQuery.isPending ? (
          <LoadingSkeletonCard />
        ) : runsQuery.isError ? (
          <ErrorState error={runsQuery.error} onRetry={() => void runsQuery.refetch()} />
        ) : runsQuery.data.items.length === 0 ? (
          <EmptyState
            title="No evaluation runs yet"
            description="Trigger a run with the CLI (--run-suite) or via POST /api/v1/admin/evaluations/runs."
          />
        ) : (
          <ul className="flex flex-col gap-3">
            {runsQuery.data.items.map((run) => (
              <RunRow key={run.run_id} run={run} />
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function RunRow({ run }: { run: QualityEvaluationRunResponse }) {
  return (
    <li>
      <Link
        href={`/admin/evaluations/${run.run_id}`}
        className="flex flex-col gap-2 rounded-card border border-border bg-surface p-4 transition-shadow hover:shadow-md focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus-ring sm:flex-row sm:items-center sm:justify-between"
      >
        <div>
          <p className="font-medium text-slate-900">{run.run_id}</p>
          <p className="text-sm text-muted">
            {run.mode} &middot; {run.completed_case_count}/{run.case_count} cases completed
            {run.failed_case_count > 0 ? `, ${run.failed_case_count} failed` : ""}
          </p>
        </div>
        <Badge tone={STATUS_TONE[run.status]}>{run.status.replace(/_/g, " ")}</Badge>
      </Link>
    </li>
  );
}

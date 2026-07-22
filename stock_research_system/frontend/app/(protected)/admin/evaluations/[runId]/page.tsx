"use client";

import { use, useEffect } from "react";
import { useRouter } from "next/navigation";

import { Badge, type BadgeTone } from "@/components/ui/Badge";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { PageHeading } from "@/components/ui/PageHeading";
import { LoadingSkeletonCard } from "@/components/ui/Skeleton";
import { MetricCard } from "@/components/evaluations/MetricCard";
import { useAuth } from "@/hooks/useAuth";
import { useEvaluationRun, useEvaluationRunMetrics, useEvaluationRunSamples } from "@/hooks/useEvaluationRuns";
import type { QualityEvaluationRunStatus, QualityGateStatus } from "@/types/api-schemas";

const RUN_STATUS_TONE: Record<QualityEvaluationRunStatus, BadgeTone> = {
  CREATED: "neutral",
  QUEUED: "neutral",
  RUNNING: "primary",
  SUCCEEDED: "success",
  PARTIALLY_SUCCEEDED: "warning",
  FAILED: "danger",
  CANCELLED: "neutral",
};

const SAMPLE_STATUS_TONE: Record<QualityGateStatus, BadgeTone> = {
  PASS: "success",
  WARN: "warning",
  FAIL: "danger",
  NOT_EVALUATED: "neutral",
};

/** ADMIN-only run detail (spec section 23): metric cards, hard-gate
 * failures, failed case ids with sanitized reasons, latency - never
 * hidden evaluator reasoning or raw learner data. */
export default function EvaluationRunDetailPage({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = use(params);
  const { account, status } = useAuth();
  const router = useRouter();
  const isAdmin = account?.role === "ADMIN";

  useEffect(() => {
    if (status === "authenticated" && !isAdmin) {
      router.replace("/dashboard");
    }
  }, [status, isAdmin, router]);

  const runQuery = useEvaluationRun(runId);
  const metricsQuery = useEvaluationRunMetrics(runId);
  const samplesQuery = useEvaluationRunSamples(runId);

  if (status !== "authenticated" || !isAdmin) {
    return <LoadingSkeletonCard />;
  }
  if (runQuery.isPending) {
    return <LoadingSkeletonCard />;
  }
  if (runQuery.isError) {
    return <ErrorState error={runQuery.error} onRetry={() => void runQuery.refetch()} />;
  }

  const run = runQuery.data;
  const aggregateMetrics = (metricsQuery.data?.items ?? []).filter((metric) => metric.sample_result_id === null);
  const hardGateFailures = aggregateMetrics.filter((metric) => metric.metric_type === "SAFETY_GATE" && metric.passed === false);
  const failedSamples = (samplesQuery.data?.items ?? []).filter((sample) => sample.failure_code);

  return (
    <div>
      <PageHeading
        title={`Run ${run.run_id.slice(0, 8)}`}
        description={`Suite ${run.suite_id.slice(0, 8)} · ${run.mode} mode · system ${run.system_version}`}
        action={<Badge tone={RUN_STATUS_TONE[run.status]}>{run.status.replace(/_/g, " ")}</Badge>}
      />

      <p className="mb-6 text-sm text-muted">
        {run.completed_case_count} of {run.case_count} cases completed, {run.failed_case_count} failed,{" "}
        {run.skipped_case_count} skipped.
        {run.status === "RUNNING" || run.status === "QUEUED" || run.status === "CREATED"
          ? " This run is still in progress and refreshes automatically."
          : ""}
      </p>

      {hardGateFailures.length > 0 ? (
        <section aria-labelledby="hard-gate-heading" className="mb-8 rounded-card border border-danger bg-danger-light p-4">
          <h2 id="hard-gate-heading" className="mb-2 text-sm font-semibold text-danger">
            Hard safety-gate failures
          </h2>
          <p className="mb-2 text-sm text-danger">
            These metrics require a score of 1.0 and are never averaged away by a high RAGAS or overall score.
          </p>
          <ul className="list-disc pl-5 text-sm text-danger">
            {hardGateFailures.map((metric) => (
              <li key={metric.metric_name}>{metric.metric_name.replace(/_/g, " ")}</li>
            ))}
          </ul>
        </section>
      ) : null}

      <section aria-labelledby="metrics-heading" className="mb-8">
        <h2 id="metrics-heading" className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted">
          Metrics
        </h2>
        {metricsQuery.isPending ? (
          <LoadingSkeletonCard />
        ) : metricsQuery.isError ? (
          <ErrorState error={metricsQuery.error} onRetry={() => void metricsQuery.refetch()} />
        ) : aggregateMetrics.length === 0 ? (
          <EmptyState title="No aggregate metrics yet" description="Metrics appear once the run completes at least one case." />
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {aggregateMetrics.map((metric) => (
              <MetricCard
                key={metric.metric_name}
                name={metric.metric_name}
                score={metric.score}
                passed={metric.passed}
                isHardGate={metric.metric_type === "SAFETY_GATE"}
              />
            ))}
          </div>
        )}
      </section>

      <section aria-labelledby="failed-cases-heading">
        <h2 id="failed-cases-heading" className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted">
          Failed cases
        </h2>
        {samplesQuery.isPending ? (
          <LoadingSkeletonCard />
        ) : samplesQuery.isError ? (
          <ErrorState error={samplesQuery.error} onRetry={() => void samplesQuery.refetch()} />
        ) : failedSamples.length === 0 ? (
          <EmptyState title="No failed cases" description="Every executed case completed without an execution failure." />
        ) : (
          <ul className="flex flex-col gap-2">
            {failedSamples.map((sample) => (
              <li key={sample.sample_result_id} className="rounded-card border border-border bg-surface p-3 text-sm">
                <p className="font-medium text-slate-900">Case {sample.case_id.slice(0, 8)}</p>
                <p className="text-muted">
                  <Badge tone={SAMPLE_STATUS_TONE[sample.status]}>{sample.status}</Badge>{" "}
                  {sample.failure_code ? `— ${sample.failure_code}` : ""}
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

"use client";

import { use, useEffect, useState } from "react";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { ErrorState } from "@/components/ui/ErrorState";
import { PageHeading } from "@/components/ui/PageHeading";
import { LoadingSkeletonCard } from "@/components/ui/Skeleton";
import { DecisionForm } from "@/components/scenarios/DecisionForm";
import { DECISION_QUALITY_LABELS, FEEDBACK_CODE_LABELS } from "@/components/scenarios/labels";
import { PriceChart } from "@/components/scenarios/PriceChart";
import { RevealPanel } from "@/components/scenarios/RevealPanel";
import { AskTutorButton } from "@/components/tutor/AskTutorButton";
import { formatCurrency, formatDate, formatPercentage } from "@/lib/formatting";
import {
  useExistingScenarioReveal,
  useRevealScenario,
  useScenario,
  useStartScenario,
  useSubmitScenarioDecision,
} from "@/hooks/useScenarios";
import type { ScenarioRevealResponse, ScenarioSubmissionResponse } from "@/types/api-schemas";

export default function ScenarioDetailPage({ params }: { params: Promise<{ scenarioId: string }> }) {
  const { scenarioId } = use(params);
  const scenarioQuery = useScenario(scenarioId);

  const [submission, setSubmission] = useState<ScenarioSubmissionResponse | null>(null);
  const [reveal, setReveal] = useState<ScenarioRevealResponse | null>(null);

  const startScenario = useStartScenario();
  const submitDecision = useSubmitScenarioDecision();
  const revealScenario = useRevealScenario();
  const existingReveal = useExistingScenarioReveal(
    submission?.submission_id ?? null,
    submission?.reveal_status === "REVEALED" && reveal === null
  );

  useEffect(() => {
    if (existingReveal.data && reveal === null) {
      setReveal(existingReveal.data);
    }
  }, [existingReveal.data, reveal]);

  if (scenarioQuery.isPending) {
    return <LoadingSkeletonCard />;
  }
  if (scenarioQuery.isError) {
    return <ErrorState error={scenarioQuery.error} onRetry={() => void scenarioQuery.refetch()} />;
  }

  const scenario = scenarioQuery.data;

  const handleStart = () => {
    startScenario.mutate(scenarioId, { onSuccess: (data) => setSubmission(data) });
  };

  const handleSubmitDecision = (input: {
    selectedOptionId: string;
    confidenceLevel: ScenarioSubmissionResponse["confidence_level"];
    rationale: string;
  }) => {
    if (!submission) return;
    submitDecision.mutate(
      {
        submissionId: submission.submission_id,
        body: {
          selected_option_id: input.selectedOptionId,
          confidence_level: input.confidenceLevel,
          learner_rationale: input.rationale || null,
        },
      },
      { onSuccess: (data) => setSubmission(data) }
    );
  };

  const handleReveal = () => {
    if (!submission) return;
    revealScenario.mutate(submission.submission_id, { onSuccess: (data) => setReveal(data) });
  };

  return (
    <div>
      <PageHeading
        title={scenario.title}
        description={scenario.description}
        action={<Badge tone="primary">{scenario.scenario_type.replace(/_/g, " ")}</Badge>}
      />

      <div className="flex flex-col gap-4">
        <div className="rounded-card border border-border bg-surface p-5">
          <h2 className="mb-2 text-sm font-semibold text-slate-900">Scenario setup</h2>
          <p className="text-sm text-slate-800">{scenario.learner_instructions}</p>
          <p className="mt-3 text-sm font-medium text-slate-900">{scenario.prompt}</p>
          {scenario.learning_objectives.length > 0 ? (
            <ul className="mt-3 list-inside list-disc text-xs text-muted">
              {scenario.learning_objectives.map((objective) => (
                <li key={objective}>{objective}</li>
              ))}
            </ul>
          ) : null}
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="rounded-card border border-border bg-surface p-5">
            <PriceChart points={scenario.focal_chart} label={scenario.focal_security.ticker} />
          </div>
          {scenario.benchmark_chart.length > 0 && scenario.benchmark_security ? (
            <div className="rounded-card border border-border bg-surface p-5">
              <PriceChart points={scenario.benchmark_chart} label={scenario.benchmark_security.ticker} color="#0FA36B" />
            </div>
          ) : null}
        </div>

        <dl className="grid grid-cols-2 gap-4 rounded-card border border-border bg-surface p-5 text-sm sm:grid-cols-4">
          <div>
            <dt className="text-xs text-muted">Decision date</dt>
            <dd className="font-semibold text-slate-900">{formatDate(scenario.decision_at)}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted">Price at decision</dt>
            <dd className="font-semibold text-slate-900">{formatCurrency(scenario.observation_metrics.decision_close)}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted">Observation return</dt>
            <dd className="font-semibold text-slate-900">
              {formatPercentage(scenario.observation_metrics.observation_return)}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-muted">Data available through</dt>
            <dd className="font-semibold text-slate-900">{formatDate(scenario.data_cutoff_at)}</dd>
          </div>
        </dl>

        {!submission ? (
          <div>
            {startScenario.isError ? <ErrorState error={startScenario.error} onRetry={handleStart} /> : null}
            <Button onClick={handleStart} isLoading={startScenario.isPending}>
              Start this scenario
            </Button>
          </div>
        ) : submission.status === "STARTED" ? (
          <div className="rounded-card border border-border bg-surface p-5">
            {submitDecision.isError ? (
              <div className="mb-3">
                <ErrorState error={submitDecision.error} />
              </div>
            ) : null}
            <DecisionForm
              options={scenario.exercise_options}
              onSubmit={handleSubmitDecision}
              isSubmitting={submitDecision.isPending}
            />
            <div className="mt-3">
              <AskTutorButton
                request={{ context_type: "SCENARIO_BEFORE_DECISION", scenario_id: scenarioId, submission_id: submission.submission_id }}
                label="Ask the tutor about this scenario"
              />
            </div>
          </div>
        ) : !reveal ? (
          <div className="rounded-card border border-border bg-surface p-5">
            {submission.decision_quality ? (
              <div className="mb-4">
                <Badge tone="primary">Decision quality: {DECISION_QUALITY_LABELS[submission.decision_quality]}</Badge>
                {submission.feedback_text ? <p className="mt-2 text-sm text-slate-800">{submission.feedback_text}</p> : null}
                {submission.feedback_codes.length > 0 ? (
                  <ul className="mt-2 list-inside list-disc text-xs text-muted">
                    {submission.feedback_codes.map((code) => (
                      <li key={code}>{FEEDBACK_CODE_LABELS[code]}</li>
                    ))}
                  </ul>
                ) : null}
              </div>
            ) : (
              <p className="mb-4 text-sm text-muted">Your decision has been recorded.</p>
            )}

            {revealScenario.isError ? (
              <div className="mb-3">
                <ErrorState error={revealScenario.error} />
              </div>
            ) : null}

            {submission.reveal_status === "AVAILABLE" ? (
              <Button onClick={handleReveal} isLoading={revealScenario.isPending}>
                Reveal what happened
              </Button>
            ) : (
              <p className="text-sm text-muted">The outcome isn&apos;t available to reveal yet.</p>
            )}
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            <RevealPanel reveal={reveal} />
            <AskTutorButton
              request={{ context_type: "SCENARIO_AFTER_REVEAL", submission_id: submission.submission_id }}
              label="Ask the tutor about this outcome"
            />
          </div>
        )}
      </div>
    </div>
  );
}

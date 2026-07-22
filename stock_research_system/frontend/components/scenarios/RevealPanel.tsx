import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { PriceChart } from "@/components/scenarios/PriceChart";
import { formatPercentage } from "@/lib/formatting";
import type { ScenarioRevealResponse } from "@/types/api-schemas";

/** Only ever render this with data returned from the reveal endpoint,
 * after the learner explicitly requested it - never before. */
export function RevealPanel({ reveal }: { reveal: ScenarioRevealResponse }) {
  const outcomeTone =
    reveal.outcome_direction === "POSITIVE" ? "success" : reveal.outcome_direction === "NEGATIVE" ? "danger" : "neutral";

  return (
    <div className="flex flex-col gap-4">
      <Alert tone="info" title="Your mastery is based on decision quality, not market luck">
        The outcome below is one possible historical result. Your feedback reflects the quality of your
        reasoning process, not whether the market happened to move in your favor.
      </Alert>

      <div className="rounded-card border border-border bg-surface p-5">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <Badge tone={outcomeTone}>{reveal.outcome_direction}</Badge>
          <span className="text-sm text-slate-700">Focal return: {formatPercentage(reveal.focal_return)}</span>
          {reveal.benchmark_return !== null ? (
            <span className="text-sm text-slate-700">Benchmark: {formatPercentage(reveal.benchmark_return)}</span>
          ) : null}
          {reveal.excess_return !== null ? (
            <span className="text-sm text-slate-700">Excess: {formatPercentage(reveal.excess_return)}</span>
          ) : null}
        </div>
        <p className="text-sm text-slate-800">{reveal.outcome_summary}</p>
        <p className="mt-2 text-sm text-slate-800">{reveal.decision_feedback}</p>
        <p className="mt-2 text-sm text-slate-800">{reveal.outcome_feedback}</p>
        <p className="mt-3 text-sm font-medium text-slate-900">{reveal.combined_learning_summary}</p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div className="rounded-card border border-border bg-surface p-5">
          <PriceChart points={reveal.future_focal_chart} label="What happened next" />
        </div>
        {reveal.future_benchmark_chart.length > 0 ? (
          <div className="rounded-card border border-border bg-surface p-5">
            <PriceChart points={reveal.future_benchmark_chart} label="Benchmark, what happened next" color="#0FA36B" />
          </div>
        ) : null}
      </div>

      <dl className="grid grid-cols-2 gap-4 text-sm sm:grid-cols-4">
        <div>
          <dt className="text-xs text-muted">Max future upside</dt>
          <dd className="font-semibold text-slate-900">{formatPercentage(reveal.maximum_future_upside)}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Max future drawdown</dt>
          <dd className="font-semibold text-slate-900">{formatPercentage(reveal.maximum_future_drawdown)}</dd>
        </div>
      </dl>
    </div>
  );
}

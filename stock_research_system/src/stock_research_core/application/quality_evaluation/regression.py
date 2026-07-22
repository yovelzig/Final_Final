"""Baseline regression comparison (spec section 18) - pure logic, no
database or evaluator access. `QualityEvaluationService.compare_with_
baseline` loads the two runs' metric summaries and calls into here.
"""

from __future__ import annotations

import math

from stock_research_core.application.quality_evaluation.models import EvaluationRegressionReport, MetricComparison
from stock_research_core.domain.quality_evaluation.enums import EvaluationComparisonResult

DEFAULT_ABSOLUTE_TOLERANCE = 0.02
DEFAULT_RELATIVE_TOLERANCE = 0.05

#: Metrics where a *lower* value is better - every other numeric metric
#: this platform produces is higher-is-better.
LOWER_IS_BETTER_METRICS: frozenset[str] = frozenset(
    {
        "confidence_brier_score",
        "confidence_calibration_error",
        "misconception_recurrence_rate",
    }
)


def _within_tolerance(candidate: float, baseline: float, *, absolute_tolerance: float, relative_tolerance: float) -> bool:
    allowed = max(absolute_tolerance, abs(baseline) * relative_tolerance)
    return abs(candidate - baseline) <= allowed


def compare_metric(
    *, metric_name: str, candidate_value: float | None, baseline_value: float | None,
    is_hard_gate: bool = False, candidate_passed: bool | None = None, baseline_passed: bool | None = None,
    absolute_tolerance: float = DEFAULT_ABSOLUTE_TOLERANCE, relative_tolerance: float = DEFAULT_RELATIVE_TOLERANCE,
) -> MetricComparison:
    if is_hard_gate:
        # Boolean hard gates: any candidate failure is a regression,
        # regardless of what the baseline did - never averaged away.
        if candidate_passed is None:
            return MetricComparison(
                metric_name=metric_name, baseline_value=baseline_value, candidate_value=candidate_value,
                result=EvaluationComparisonResult.NOT_COMPARABLE, detail="hard gate not evaluated in candidate run",
            )
        if candidate_passed is False:
            return MetricComparison(
                metric_name=metric_name, baseline_value=baseline_value, candidate_value=candidate_value,
                result=EvaluationComparisonResult.REGRESSED, detail="hard-gate failure",
            )
        result = EvaluationComparisonResult.IMPROVED if baseline_passed is False else EvaluationComparisonResult.UNCHANGED
        return MetricComparison(
            metric_name=metric_name, baseline_value=baseline_value, candidate_value=candidate_value, result=result,
        )

    if candidate_value is None or baseline_value is None:
        return MetricComparison(
            metric_name=metric_name, baseline_value=baseline_value, candidate_value=candidate_value,
            result=EvaluationComparisonResult.NOT_COMPARABLE, detail="metric missing from one of the two runs",
        )
    if not math.isfinite(candidate_value) or not math.isfinite(baseline_value):
        return MetricComparison(
            metric_name=metric_name, baseline_value=baseline_value, candidate_value=candidate_value,
            result=EvaluationComparisonResult.NOT_COMPARABLE, detail="non-finite metric value",
        )

    if _within_tolerance(
        candidate_value, baseline_value, absolute_tolerance=absolute_tolerance, relative_tolerance=relative_tolerance
    ):
        return MetricComparison(
            metric_name=metric_name, baseline_value=baseline_value, candidate_value=candidate_value,
            result=EvaluationComparisonResult.UNCHANGED,
        )

    lower_is_better = metric_name in LOWER_IS_BETTER_METRICS
    candidate_is_better = (candidate_value < baseline_value) if lower_is_better else (candidate_value > baseline_value)
    result = EvaluationComparisonResult.IMPROVED if candidate_is_better else EvaluationComparisonResult.REGRESSED
    return MetricComparison(
        metric_name=metric_name, baseline_value=baseline_value, candidate_value=candidate_value, result=result,
    )


def build_regression_report(
    *, run_id, baseline_id, candidate_suite_version: str, baseline_suite_version: str,
    candidate_evaluator_model: str | None, baseline_evaluator_model: str | None,
    comparisons: list[MetricComparison],
) -> EvaluationRegressionReport:
    notes: list[str] = []
    comparable = True

    if candidate_suite_version != baseline_suite_version:
        comparable = False
        notes.append(
            f"Suite version changed ({baseline_suite_version} -> {candidate_suite_version}) - "
            "not directly comparable without an explicit compatibility mapping."
        )
    if candidate_evaluator_model != baseline_evaluator_model and (candidate_evaluator_model or baseline_evaluator_model):
        notes.append(
            f"Evaluator model changed ({baseline_evaluator_model!r} -> {candidate_evaluator_model!r}) - "
            "judge-dependent metric comparisons are evaluator-model-dependent; do not treat as pure improvement."
        )

    if not comparable:
        overall = EvaluationComparisonResult.NOT_COMPARABLE
    elif any(comparison.result == EvaluationComparisonResult.REGRESSED for comparison in comparisons):
        overall = EvaluationComparisonResult.REGRESSED
    elif any(comparison.result == EvaluationComparisonResult.IMPROVED for comparison in comparisons):
        overall = EvaluationComparisonResult.IMPROVED
    elif all(comparison.result == EvaluationComparisonResult.NOT_COMPARABLE for comparison in comparisons):
        overall = EvaluationComparisonResult.NOT_COMPARABLE
    else:
        overall = EvaluationComparisonResult.UNCHANGED

    return EvaluationRegressionReport(
        run_id=run_id, baseline_id=baseline_id, comparable=comparable, overall_result=overall,
        metric_comparisons=comparisons, notes=notes,
    )

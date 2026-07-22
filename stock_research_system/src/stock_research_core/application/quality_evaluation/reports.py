"""Report-assembly helpers for the Phase 13 quality-evaluation platform -
pure functions turning collected per-case metric results into the
run-level summaries `QualityEvaluationService` returns/persists.
"""

from __future__ import annotations

from statistics import mean

from stock_research_core.application.quality_evaluation.deterministic_metrics import HARD_GATE_METRIC_NAMES
from stock_research_core.application.quality_evaluation.models import DeterministicMetricResult, QualityGateDecision
from stock_research_core.domain.quality_evaluation.enums import QualityGateStatus


def summarize_scores(metric_results: list[DeterministicMetricResult]) -> dict[str, float]:
    """Mean score per metric name across every case that had a score for
    it - metrics with `score is None` (NOT_EVALUATED) for a case are
    excluded from that metric's average rather than counted as 0."""
    by_name: dict[str, list[float]] = {}
    for result in metric_results:
        if result.score is not None:
            by_name.setdefault(result.metric_name, []).append(result.score)
    return {name: mean(scores) for name, scores in by_name.items() if scores}


def build_gate_decision(metric_results: list[DeterministicMetricResult]) -> QualityGateDecision:
    """Deterministic hard-gate failures always dominate the overall
    verdict - never averaged away by a high RAGAS score (spec section 13).
    A hard gate that was never evaluated for any case is treated as a
    warning, not silently ignored."""
    hard_gate_failures: list[str] = []
    warnings: list[str] = []
    seen_hard_gates: set[str] = set()

    for result in metric_results:
        if not result.is_hard_gate:
            if result.gate_status == QualityGateStatus.WARN:
                warnings.append(result.metric_name)
            continue
        seen_hard_gates.add(result.metric_name)
        if result.gate_status == QualityGateStatus.FAIL:
            hard_gate_failures.append(result.metric_name)

    unevaluated_hard_gates = HARD_GATE_METRIC_NAMES - seen_hard_gates
    for name in sorted(unevaluated_hard_gates):
        warnings.append(f"{name} (not evaluated by this suite)")

    if hard_gate_failures:
        overall_status = QualityGateStatus.FAIL
    elif warnings:
        overall_status = QualityGateStatus.WARN
    else:
        overall_status = QualityGateStatus.PASS

    return QualityGateDecision(
        overall_status=overall_status, hard_gate_failures=sorted(set(hard_gate_failures)), warnings=sorted(set(warnings)),
    )

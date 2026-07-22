"""Unit tests for `application.quality_evaluation.regression`."""

from __future__ import annotations

from uuid import uuid4

from stock_research_core.application.quality_evaluation.regression import build_regression_report, compare_metric
from stock_research_core.domain.quality_evaluation.enums import EvaluationComparisonResult


class TestCompareMetricNumeric:
    def test_within_tolerance_is_unchanged(self) -> None:
        comparison = compare_metric(metric_name="hit_at_5", candidate_value=0.81, baseline_value=0.80)
        assert comparison.result == EvaluationComparisonResult.UNCHANGED

    def test_higher_is_better_improvement(self) -> None:
        comparison = compare_metric(metric_name="hit_at_5", candidate_value=0.95, baseline_value=0.60)
        assert comparison.result == EvaluationComparisonResult.IMPROVED

    def test_higher_is_better_regression(self) -> None:
        comparison = compare_metric(metric_name="hit_at_5", candidate_value=0.40, baseline_value=0.80)
        assert comparison.result == EvaluationComparisonResult.REGRESSED

    def test_lower_is_better_metric_improvement_means_lower_value(self) -> None:
        comparison = compare_metric(metric_name="confidence_brier_score", candidate_value=0.05, baseline_value=0.30)
        assert comparison.result == EvaluationComparisonResult.IMPROVED

    def test_lower_is_better_metric_regression_means_higher_value(self) -> None:
        comparison = compare_metric(metric_name="confidence_brier_score", candidate_value=0.50, baseline_value=0.10)
        assert comparison.result == EvaluationComparisonResult.REGRESSED

    def test_missing_metric_is_not_comparable(self) -> None:
        comparison = compare_metric(metric_name="hit_at_5", candidate_value=None, baseline_value=0.5)
        assert comparison.result == EvaluationComparisonResult.NOT_COMPARABLE

    def test_non_finite_value_is_not_comparable(self) -> None:
        comparison = compare_metric(metric_name="hit_at_5", candidate_value=float("nan"), baseline_value=0.5)
        assert comparison.result == EvaluationComparisonResult.NOT_COMPARABLE


class TestCompareMetricHardGate:
    def test_candidate_failure_is_always_regression(self) -> None:
        comparison = compare_metric(
            metric_name="citation_validity", candidate_value=None, baseline_value=None,
            is_hard_gate=True, candidate_passed=False, baseline_passed=True,
        )
        assert comparison.result == EvaluationComparisonResult.REGRESSED

    def test_candidate_failure_is_regression_even_if_baseline_also_failed(self) -> None:
        comparison = compare_metric(
            metric_name="citation_validity", candidate_value=None, baseline_value=None,
            is_hard_gate=True, candidate_passed=False, baseline_passed=False,
        )
        assert comparison.result == EvaluationComparisonResult.REGRESSED

    def test_candidate_pass_after_baseline_failure_is_improved(self) -> None:
        comparison = compare_metric(
            metric_name="citation_validity", candidate_value=None, baseline_value=None,
            is_hard_gate=True, candidate_passed=True, baseline_passed=False,
        )
        assert comparison.result == EvaluationComparisonResult.IMPROVED

    def test_candidate_pass_after_baseline_pass_is_unchanged(self) -> None:
        comparison = compare_metric(
            metric_name="citation_validity", candidate_value=None, baseline_value=None,
            is_hard_gate=True, candidate_passed=True, baseline_passed=True,
        )
        assert comparison.result == EvaluationComparisonResult.UNCHANGED

    def test_not_evaluated_hard_gate_is_not_comparable(self) -> None:
        comparison = compare_metric(
            metric_name="citation_validity", candidate_value=None, baseline_value=None,
            is_hard_gate=True, candidate_passed=None, baseline_passed=True,
        )
        assert comparison.result == EvaluationComparisonResult.NOT_COMPARABLE


class TestBuildRegressionReport:
    def test_hard_gate_regression_dominates_overall_result(self) -> None:
        comparisons = [
            compare_metric(metric_name="hit_at_5", candidate_value=0.95, baseline_value=0.5),  # improved
            compare_metric(
                metric_name="citation_validity", candidate_value=None, baseline_value=None,
                is_hard_gate=True, candidate_passed=False, baseline_passed=True,
            ),  # regressed
        ]
        report = build_regression_report(
            run_id=uuid4(), baseline_id=uuid4(), candidate_suite_version="v1", baseline_suite_version="v1",
            candidate_evaluator_model=None, baseline_evaluator_model=None, comparisons=comparisons,
        )
        assert report.overall_result == EvaluationComparisonResult.REGRESSED
        assert report.comparable is True

    def test_different_suite_versions_are_not_comparable(self) -> None:
        report = build_regression_report(
            run_id=uuid4(), baseline_id=uuid4(), candidate_suite_version="v2", baseline_suite_version="v1",
            candidate_evaluator_model=None, baseline_evaluator_model=None, comparisons=[],
        )
        assert report.comparable is False
        assert report.overall_result == EvaluationComparisonResult.NOT_COMPARABLE
        assert any("Suite version changed" in note for note in report.notes)

    def test_evaluator_model_change_is_noted_but_still_comparable(self) -> None:
        report = build_regression_report(
            run_id=uuid4(), baseline_id=uuid4(), candidate_suite_version="v1", baseline_suite_version="v1",
            candidate_evaluator_model="judge-2", baseline_evaluator_model="judge-1", comparisons=[],
        )
        assert report.comparable is True
        assert any("Evaluator model changed" in note for note in report.notes)

    def test_all_unchanged_is_unchanged_overall(self) -> None:
        comparisons = [compare_metric(metric_name="hit_at_5", candidate_value=0.80, baseline_value=0.80)]
        report = build_regression_report(
            run_id=uuid4(), baseline_id=uuid4(), candidate_suite_version="v1", baseline_suite_version="v1",
            candidate_evaluator_model=None, baseline_evaluator_model=None, comparisons=comparisons,
        )
        assert report.overall_result == EvaluationComparisonResult.UNCHANGED

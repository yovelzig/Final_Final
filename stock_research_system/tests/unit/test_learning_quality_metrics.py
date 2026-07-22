"""Unit tests for `application.quality_evaluation.learning_metrics`."""

from __future__ import annotations

import pytest

from stock_research_core.application.quality_evaluation.learning_metrics import (
    completion_rate,
    confidence_brier_score,
    confidence_label_to_probability,
    expected_calibration_error,
    mastery_gain,
    misconception_recurrence_rate,
    normalized_learning_gain,
    raw_retention_change,
    retention_ratio,
    risk_identification_gain,
    scenario_decision_quality_gain,
)


def test_mastery_gain() -> None:
    assert mastery_gain(pre_mastery_score=0.4, post_mastery_score=0.7) == pytest.approx(0.3)


class TestNormalizedLearningGain:
    def test_typical_gain(self) -> None:
        gain = normalized_learning_gain(pre_score=0.4, post_score=0.7)
        assert gain == pytest.approx(0.5)  # (0.7-0.4)/(1-0.4)

    def test_perfect_pre_score_is_not_applicable(self) -> None:
        assert normalized_learning_gain(pre_score=1.0, post_score=1.0) is None

    def test_never_divides_by_zero(self) -> None:
        # pre_score > 1 would be an invalid input from the caller, but the
        # >= 1 guard must still prevent a ZeroDivisionError.
        assert normalized_learning_gain(pre_score=1.0, post_score=0.5) is None


class TestRetention:
    def test_raw_retention_change(self) -> None:
        assert raw_retention_change(immediate_post_learning_score=0.8, delayed_review_score=0.6) == pytest.approx(-0.2)

    def test_retention_ratio(self) -> None:
        assert retention_ratio(immediate_post_learning_score=0.8, delayed_review_score=0.4) == pytest.approx(0.5)

    def test_retention_ratio_none_when_denominator_not_positive(self) -> None:
        assert retention_ratio(immediate_post_learning_score=0.0, delayed_review_score=0.5) is None


class TestMisconceptionRecurrence:
    def test_typical_rate(self) -> None:
        assert misconception_recurrence_rate(repeated_evidence_count=1, eligible_opportunity_count=4) == pytest.approx(0.25)

    def test_no_eligible_opportunities_is_none(self) -> None:
        assert misconception_recurrence_rate(repeated_evidence_count=0, eligible_opportunity_count=0) is None

    def test_repeated_cannot_exceed_eligible(self) -> None:
        with pytest.raises(ValueError):
            misconception_recurrence_rate(repeated_evidence_count=5, eligible_opportunity_count=2)


class TestConfidenceBrierScore:
    def test_known_mapping_values(self) -> None:
        assert confidence_label_to_probability("VERY_LOW") == 0.10
        assert confidence_label_to_probability("HIGH") == 0.70

    def test_unknown_label_raises(self) -> None:
        with pytest.raises(ValueError):
            confidence_label_to_probability("SUPER_DUPER_SURE")

    def test_perfect_calibration_high_confidence_correct(self) -> None:
        score = confidence_brier_score(predictions=[("VERY_HIGH", True)])
        assert score == pytest.approx((0.9 - 1.0) ** 2)

    def test_empty_predictions_is_none(self) -> None:
        assert confidence_brier_score(predictions=[]) is None

    def test_lower_is_better(self) -> None:
        overconfident_and_wrong = confidence_brier_score(predictions=[("VERY_HIGH", False)])
        well_calibrated = confidence_brier_score(predictions=[("MEDIUM", True)])
        assert overconfident_and_wrong > well_calibrated


class TestExpectedCalibrationError:
    def test_perfectly_calibrated_bin_has_zero_error(self) -> None:
        # 5 predictions at probability ~0.7, 70% of them correct.
        predictions = [(0.7, True)] * 7 + [(0.7, False)] * 3
        ece, bins = expected_calibration_error(predictions=predictions, minimum_bin_samples=5)
        assert ece == pytest.approx(0.0, abs=1e-9)

    def test_bins_below_minimum_sample_size_are_excluded(self) -> None:
        predictions = [(0.1, True), (0.1, True)]  # only 2 samples, below default minimum of 5
        ece, bins = expected_calibration_error(predictions=predictions, minimum_bin_samples=5)
        assert ece is None
        assert all(not b.included for b in bins)

    def test_out_of_range_probability_raises(self) -> None:
        with pytest.raises(ValueError):
            expected_calibration_error(predictions=[(1.5, True)])

    def test_probability_exactly_one_falls_in_last_bin(self) -> None:
        predictions = [(1.0, True)] * 5
        ece, bins = expected_calibration_error(predictions=predictions, minimum_bin_samples=5)
        assert bins[-1].sample_count == 5
        assert ece == pytest.approx(0.0)


class TestScenarioAndRiskGains:
    def test_scenario_decision_quality_gain(self) -> None:
        assert scenario_decision_quality_gain(
            earlier_decision_quality_score=0.4, later_decision_quality_score=0.6
        ) == pytest.approx(0.2)

    def test_risk_identification_gain(self) -> None:
        assert risk_identification_gain(
            earlier_risk_identification_score=0.3, later_risk_identification_score=0.5
        ) == pytest.approx(0.2)


class TestCompletionRate:
    def test_typical_rate(self) -> None:
        assert completion_rate(completed_count=3, eligible_count=4) == pytest.approx(0.75)

    def test_no_eligible_is_none(self) -> None:
        assert completion_rate(completed_count=0, eligible_count=0) is None

    def test_completed_cannot_exceed_eligible(self) -> None:
        with pytest.raises(ValueError):
            completion_rate(completed_count=5, eligible_count=2)

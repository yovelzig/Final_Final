"""Learning-outcome metric calculators (spec section 15) - pure
functions over already-fetched FinQuest records (mastery scores,
review-schedule scores, misconception evidence, confidence labels,
scenario/portfolio-risk scores, completion counts). These evaluate
*educational outcomes*, not RAG or Coach quality, and are strictly
observational: nothing here claims the Coach or the RAG tutor *caused*
an improvement (spec section 15's interpretation requirements) - that
labeling is the caller's responsibility when presenting results.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Version tag stored alongside every calculated aggregate
#: (`LearningQualityAggregate.calculation_version`) - bump whenever the
#: mapping or bin boundaries below change, since that changes the
#: meaning of previously stored aggregates.
CALCULATION_VERSION = "learning-metrics-v1"

#: Confidence-label -> predicted-probability mapping (spec section 15.5).
#: Versioned via `CALCULATION_VERSION` above.
CONFIDENCE_TO_PROBABILITY: dict[str, float] = {
    "VERY_LOW": 0.10,
    "LOW": 0.30,
    "MEDIUM": 0.50,
    "HIGH": 0.70,
    "VERY_HIGH": 0.90,
}

#: Fixed calibration bins (spec section 15.6), each `[lower, upper)`
#: except the last, which is `[lower, upper]`.
CALIBRATION_BIN_BOUNDARIES: tuple[float, ...] = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)

#: A calibration bin with fewer than this many predictions is excluded
#: from the ECE average entirely (too few samples to be meaningful) -
#: never treated as zero error.
MINIMUM_CALIBRATION_BIN_SAMPLES = 5


def mastery_gain(*, pre_mastery_score: float, post_mastery_score: float) -> float:
    return post_mastery_score - pre_mastery_score


def normalized_learning_gain(*, pre_score: float, post_score: float) -> float | None:
    """`None` (not applicable) when `pre_score == 1` - there is no room
    left to normalize a gain into, and the spec explicitly forbids
    dividing by zero here."""
    if pre_score >= 1:
        return None
    return (post_score - pre_score) / (1 - pre_score)


def raw_retention_change(*, immediate_post_learning_score: float, delayed_review_score: float) -> float:
    return delayed_review_score - immediate_post_learning_score


def retention_ratio(*, immediate_post_learning_score: float, delayed_review_score: float) -> float | None:
    """`None` when the denominator is not positive - a ratio against a
    zero (or negative, if ever possible) immediate score is meaningless,
    not "very high retention"."""
    if immediate_post_learning_score <= 0:
        return None
    return delayed_review_score / immediate_post_learning_score


def misconception_recurrence_rate(*, repeated_evidence_count: int, eligible_opportunity_count: int) -> float | None:
    """`eligible_opportunity_count` is every later exercise/scenario
    attempt targeting a skill the learner previously showed this
    misconception on and was marked improved/resolved for -
    `repeated_evidence_count` is how many of those attempts showed the
    same misconception again. `None` when there were no eligible
    opportunities (nothing to measure recurrence against)."""
    if eligible_opportunity_count <= 0:
        return None
    if repeated_evidence_count > eligible_opportunity_count:
        raise ValueError("repeated_evidence_count cannot exceed eligible_opportunity_count")
    return repeated_evidence_count / eligible_opportunity_count


def confidence_label_to_probability(label: str) -> float:
    try:
        return CONFIDENCE_TO_PROBABILITY[label]
    except KeyError as exc:
        raise ValueError(f"Unknown confidence label {label!r} - expected one of {sorted(CONFIDENCE_TO_PROBABILITY)}") from exc


def confidence_brier_score(*, predictions: list[tuple[str, bool]]) -> float | None:
    """`predictions` is `(confidence_label, was_correct)` pairs. Lower is
    better (0 = perfectly calibrated and correct). `None` when there are
    no predictions to score."""
    if not predictions:
        return None
    total = 0.0
    for label, correct in predictions:
        probability = confidence_label_to_probability(label)
        outcome = 1.0 if correct else 0.0
        total += (probability - outcome) ** 2
    return total / len(predictions)


@dataclass(frozen=True)
class CalibrationBinResult:
    lower: float
    upper: float
    sample_count: int
    mean_predicted_probability: float | None
    empirical_accuracy: float | None
    included: bool


def expected_calibration_error(
    *, predictions: list[tuple[float, bool]], minimum_bin_samples: int = MINIMUM_CALIBRATION_BIN_SAMPLES,
) -> tuple[float | None, list[CalibrationBinResult]]:
    """`predictions` is `(predicted_probability, was_correct)` pairs.
    Returns `(ece, per_bin_detail)`; `ece` is `None` when every bin was
    excluded for having too few samples. Lower is better."""
    bins: list[list[tuple[float, bool]]] = [[] for _ in range(len(CALIBRATION_BIN_BOUNDARIES) - 1)]
    for probability, correct in predictions:
        if not 0.0 <= probability <= 1.0:
            raise ValueError(f"predicted_probability must be in [0, 1], got {probability}")
        bin_index = min(
            int(probability * (len(CALIBRATION_BIN_BOUNDARIES) - 1)), len(CALIBRATION_BIN_BOUNDARIES) - 2
        )
        bins[bin_index].append((probability, correct))

    results: list[CalibrationBinResult] = []
    weighted_error_sum = 0.0
    included_sample_count = 0
    for index, bin_predictions in enumerate(bins):
        lower, upper = CALIBRATION_BIN_BOUNDARIES[index], CALIBRATION_BIN_BOUNDARIES[index + 1]
        sample_count = len(bin_predictions)
        included = sample_count >= minimum_bin_samples
        mean_probability = sum(p for p, _ in bin_predictions) / sample_count if sample_count else None
        accuracy = sum(1 for _, c in bin_predictions if c) / sample_count if sample_count else None
        results.append(
            CalibrationBinResult(
                lower=lower, upper=upper, sample_count=sample_count, mean_predicted_probability=mean_probability,
                empirical_accuracy=accuracy, included=included,
            )
        )
        if included:
            weighted_error_sum += sample_count * abs(mean_probability - accuracy)
            included_sample_count += sample_count

    ece = weighted_error_sum / included_sample_count if included_sample_count > 0 else None
    return ece, results


def scenario_decision_quality_gain(*, earlier_decision_quality_score: float, later_decision_quality_score: float) -> float:
    """Never uses realized market return - both scores must already be
    decision-quality scores (spec section 15.7 explicitly forbids
    outcome-based scoring here)."""
    return later_decision_quality_score - earlier_decision_quality_score


def risk_identification_gain(*, earlier_risk_identification_score: float, later_risk_identification_score: float) -> float:
    return later_risk_identification_score - earlier_risk_identification_score


def completion_rate(*, completed_count: int, eligible_count: int) -> float | None:
    if eligible_count <= 0:
        return None
    if completed_count > eligible_count:
        raise ValueError("completed_count cannot exceed eligible_count")
    return completed_count / eligible_count

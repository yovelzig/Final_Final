"""Unit tests for `RuleBasedDifficultyPolicy` (difficulty-policy-v1)."""

from __future__ import annotations

from stock_research_core.application.adaptive_learning.policies import RuleBasedDifficultyPolicy
from stock_research_core.domain.adaptive_learning.enums import DifficultyAdjustment
from stock_research_core.domain.learning.enums import ConfidenceLevel

POLICY = RuleBasedDifficultyPolicy()


def test_policy_version_is_stable() -> None:
    assert POLICY.policy_version == "difficulty-policy-v1"


def test_mastery_bands_select_expected_targets() -> None:
    score, adjustment = POLICY.recommend_difficulty(
        mastery_score=0.10,
        recent_correct_rate=None,
        consecutive_correct=0,
        consecutive_incorrect=0,
        confidence_level=None,
    )
    assert (score, adjustment) == (0.20, DifficultyAdjustment.KEEP)

    score, _ = POLICY.recommend_difficulty(
        mastery_score=0.45,
        recent_correct_rate=None,
        consecutive_correct=0,
        consecutive_incorrect=0,
        confidence_level=None,
    )
    assert score == 0.40

    score, _ = POLICY.recommend_difficulty(
        mastery_score=0.70,
        recent_correct_rate=None,
        consecutive_correct=0,
        consecutive_incorrect=0,
        confidence_level=None,
    )
    assert score == 0.60

    score, _ = POLICY.recommend_difficulty(
        mastery_score=0.90,
        recent_correct_rate=None,
        consecutive_correct=0,
        consecutive_incorrect=0,
        confidence_level=None,
    )
    assert score == 0.80


def test_consecutive_incorrect_decreases_difficulty() -> None:
    score, adjustment = POLICY.recommend_difficulty(
        mastery_score=0.45,
        recent_correct_rate=0.0,
        consecutive_correct=0,
        consecutive_incorrect=2,
        confidence_level=None,
    )
    assert adjustment == DifficultyAdjustment.DECREASE
    assert score == 0.40 - 0.15


def test_high_confidence_miss_adds_additional_penalty() -> None:
    score, adjustment = POLICY.recommend_difficulty(
        mastery_score=0.45,
        recent_correct_rate=0.0,
        consecutive_correct=0,
        consecutive_incorrect=1,
        confidence_level=ConfidenceLevel.HIGH,
    )
    assert adjustment == DifficultyAdjustment.DECREASE
    assert round(score, 2) == round(0.40 - 0.10, 2)


def test_decrease_takes_precedence_over_increase() -> None:
    """2+ consecutive incorrect always wins even if a correct streak also occurred before it."""
    score, adjustment = POLICY.recommend_difficulty(
        mastery_score=0.45,
        recent_correct_rate=0.5,
        consecutive_correct=3,
        consecutive_incorrect=2,
        confidence_level=None,
    )
    assert adjustment == DifficultyAdjustment.DECREASE
    assert score == 0.40 - 0.15


def test_consecutive_correct_increases_difficulty() -> None:
    score, adjustment = POLICY.recommend_difficulty(
        mastery_score=0.45,
        recent_correct_rate=1.0,
        consecutive_correct=3,
        consecutive_incorrect=0,
        confidence_level=ConfidenceLevel.MEDIUM,
    )
    assert adjustment == DifficultyAdjustment.INCREASE
    assert score == 0.40 + 0.10


def test_low_confidence_streak_never_increases_difficulty() -> None:
    score, adjustment = POLICY.recommend_difficulty(
        mastery_score=0.45,
        recent_correct_rate=1.0,
        consecutive_correct=5,
        consecutive_incorrect=0,
        confidence_level=ConfidenceLevel.LOW,
    )
    assert adjustment == DifficultyAdjustment.KEEP
    assert score == 0.40


def test_score_is_clamped_to_unit_interval() -> None:
    score, _ = POLICY.recommend_difficulty(
        mastery_score=0.95,
        recent_correct_rate=1.0,
        consecutive_correct=10,
        consecutive_incorrect=0,
        confidence_level=ConfidenceLevel.VERY_HIGH,
    )
    assert score <= 1.0

    score, _ = POLICY.recommend_difficulty(
        mastery_score=0.10,
        recent_correct_rate=0.0,
        consecutive_correct=0,
        consecutive_incorrect=10,
        confidence_level=ConfidenceLevel.HIGH,
    )
    assert score >= 0.0


def test_recommendation_is_deterministic_for_identical_inputs() -> None:
    kwargs = dict(
        mastery_score=0.5,
        recent_correct_rate=0.5,
        consecutive_correct=1,
        consecutive_incorrect=0,
        confidence_level=ConfidenceLevel.MEDIUM,
    )
    first = POLICY.recommend_difficulty(**kwargs)
    second = POLICY.recommend_difficulty(**kwargs)
    assert first == second

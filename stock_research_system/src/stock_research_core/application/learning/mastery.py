"""Deterministic skill-mastery calculation.

No machine learning: `DeterministicMasteryCalculator` implements a
single, versioned, explicit rule ("mastery-v1"). It is isolated behind
`MasteryCalculatorPort` so a future phase can swap in a different
algorithm without touching `LearningService`.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from stock_research_core.domain.learning.enums import MasteryLevel
from stock_research_core.domain.learning.models import SkillMastery

MASTERY_CALCULATION_VERSION = "mastery-v1"

_PREVIOUS_WEIGHT = 0.8
_LATEST_WEIGHT = 0.2
_MINIMUM_ATTEMPTS_FOR_MASTERED = 3

_NOVICE_MAX = 0.30
_DEVELOPING_MAX = 0.60
_PROFICIENT_MAX = 0.85

_REVIEW_INTERVAL_DAYS: dict[MasteryLevel, int] = {
    MasteryLevel.NOT_ASSESSED: 1,
    MasteryLevel.NOVICE: 1,
    MasteryLevel.DEVELOPING: 3,
    MasteryLevel.PROFICIENT: 7,
    MasteryLevel.MASTERED: 14,
}


class MasteryCalculatorPort(Protocol):
    """Computes an updated `SkillMastery` from new graded-attempt evidence."""

    calculation_version: str

    def update(
        self,
        *,
        learner_id: UUID,
        skill_id: UUID,
        previous: SkillMastery | None,
        latest_score_normalized: float,
        is_correct: bool,
        now: datetime,
    ) -> SkillMastery: ...


def _mastery_level_for(mastery_score: float, total_attempts: int) -> MasteryLevel:
    """mastery-v1 level thresholds.

    NOVICE:      score <  0.30
    DEVELOPING:  0.30 <= score < 0.60
    PROFICIENT:  0.60 <= score < 0.85, or score >= 0.85 with fewer than 3 graded attempts
    MASTERED:    score >= 0.85 and at least 3 graded attempts (sufficient evidence)
    """
    if mastery_score < _NOVICE_MAX:
        return MasteryLevel.NOVICE
    if mastery_score < _DEVELOPING_MAX:
        return MasteryLevel.DEVELOPING
    if mastery_score < _PROFICIENT_MAX:
        return MasteryLevel.PROFICIENT
    if total_attempts >= _MINIMUM_ATTEMPTS_FOR_MASTERED:
        return MasteryLevel.MASTERED
    return MasteryLevel.PROFICIENT


class DeterministicMasteryCalculator:
    """mastery-v1: an explicit, versioned, non-ML mastery update rule.

    - First graded attempt for a skill: `mastery_score` is simply the
      normalized score (0..1) of that attempt.
    - Every subsequent attempt: `mastery_score = 0.8 * previous_score +
      0.2 * latest_normalized_score` - an exponential moving average
      that favors established performance over any single attempt.
    - `consecutive_correct` increments on a correct attempt and resets
      to 0 otherwise.
    - `MASTERED` requires `mastery_score >= 0.85` AND at least 3 total
      graded attempts for that skill; otherwise the level caps at
      `PROFICIENT` even once the score alone clears 0.85.
    """

    calculation_version = MASTERY_CALCULATION_VERSION

    def update(
        self,
        *,
        learner_id: UUID,
        skill_id: UUID,
        previous: SkillMastery | None,
        latest_score_normalized: float,
        is_correct: bool,
        now: datetime,
    ) -> SkillMastery:
        if not 0.0 <= latest_score_normalized <= 1.0:
            raise ValueError("latest_score_normalized must be between 0 and 1")

        if previous is None:
            mastery_score = latest_score_normalized
            correct_attempts = 1 if is_correct else 0
            total_attempts = 1
            consecutive_correct = 1 if is_correct else 0
            mastery_id = uuid4()
        else:
            mastery_score = (
                _PREVIOUS_WEIGHT * previous.mastery_score
                + _LATEST_WEIGHT * latest_score_normalized
            )
            correct_attempts = previous.correct_attempts + (1 if is_correct else 0)
            total_attempts = previous.total_attempts + 1
            consecutive_correct = previous.consecutive_correct + 1 if is_correct else 0
            mastery_id = previous.mastery_id

        mastery_level = _mastery_level_for(mastery_score, total_attempts)
        review_interval = timedelta(days=_REVIEW_INTERVAL_DAYS[mastery_level])

        return SkillMastery(
            mastery_id=mastery_id,
            learner_id=learner_id,
            skill_id=skill_id,
            mastery_score=mastery_score,
            mastery_level=mastery_level,
            correct_attempts=correct_attempts,
            total_attempts=total_attempts,
            consecutive_correct=consecutive_correct,
            last_practiced_at=now,
            next_review_at=now + review_interval,
            calculation_version=self.calculation_version,
            updated_at=now,
        )

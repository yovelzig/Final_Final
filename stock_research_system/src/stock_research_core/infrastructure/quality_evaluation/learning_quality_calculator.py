"""`LearningQualityCalculatorPort` implementation.

Scope note: the pure per-learner calculation formulas (mastery gain,
normalized gain, retention, misconception recurrence, Brier/calibration,
scenario/risk gain, completion rate) are complete and fully unit-tested
in `application.quality_evaluation.learning_metrics`. Wiring them up to
real *cohort-wide* data is a follow-up: today's repository ports
(`ProgressRepositoryPort.list_for_learner`,
`LearningSessionRepositoryPort.list_active_sessions`, etc.) are
per-learner, not bulk/cohort-queryable, and adding new bulk-query
methods to five different existing repositories is out of scope for
this pass. This adapter therefore satisfies `LearningQualityCalculatorPort`
(so job/service wiring type-checks and constructs cleanly) but raises a
clear, typed error rather than silently returning fabricated aggregates.
"""

from __future__ import annotations

from datetime import datetime

from stock_research_core.domain.quality_evaluation.enums import LearningOutcomeMetricType
from stock_research_core.domain.quality_evaluation.models import LearningQualityAggregate


class LearningQualityDataNotAvailableError(NotImplementedError):
    """Raised when cohort-wide source data for a learning-outcome metric
    is not yet queryable - never silently substituted with a fabricated
    or partial aggregate."""


class NotYetImplementedLearningQualityCalculator:
    async def calculate(
        self, *, metric_type: LearningOutcomeMetricType, period_start: datetime, period_end: datetime,
        cohort_dimensions: list[str], calculation_version: str,
    ) -> list[LearningQualityAggregate]:
        raise LearningQualityDataNotAvailableError(
            f"Cohort-wide data fetching for {metric_type.value} is not wired up yet - "
            "the calculation formula itself is implemented and tested in "
            "application.quality_evaluation.learning_metrics."
        )

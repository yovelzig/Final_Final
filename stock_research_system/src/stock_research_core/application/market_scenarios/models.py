"""Learner-safe application-level result models for historical market
scenarios.

These are the *only* objects a learner-facing caller (the CLI, and
later an API) should ever see before a submission is graded and
revealed. `LearnerScenarioView` in particular must never be able to
carry a future bar, a future-derived metric, a rubric score, or an
`is_correct` flag - enforced structurally by simply not declaring those
fields (this codebase's `DomainModel` base uses `extra="forbid"`, so no
caller can smuggle one in either) plus an explicit point-in-time
validator below.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field, model_validator

from stock_research_core.application.learning.models import LearningActivityResult
from stock_research_core.domain.learning.enums import DifficultyLevel
from stock_research_core.domain.market_scenarios.enums import (
    MarketScenarioType,
    ScenarioRevealStatus,
)
from stock_research_core.domain.market_scenarios.models import (
    HistoricalMarketScenario,
    ScenarioObservationMetrics,
    ScenarioOutcome,
    ScenarioSubmission,
)
from stock_research_core.domain.models import DomainModel, Security


class ScenarioChartPoint(DomainModel):
    """One OHLCV point rendered for a learner. Whether a given point is
    allowed to appear in a particular view (i.e. not later than that
    view's cutoff) is enforced by the container model
    (`LearnerScenarioView`/`ScenarioReveal`), not here - this model only
    guarantees internal OHLC consistency.
    """

    timestamp: datetime
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    adjusted_close: float = Field(gt=0)
    volume: int = Field(ge=0)

    @model_validator(mode="after")
    def _validate_point(self) -> ScenarioChartPoint:
        if self.timestamp.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        if self.high < self.open or self.high < self.close or self.high < self.low:
            raise ValueError("high must be greater than or equal to open, close, and low")
        if self.low > self.open or self.low > self.close or self.low > self.high:
            raise ValueError("low must be less than or equal to open, close, and high")
        return self


class LearnerSafeExerciseOption(DomainModel):
    """An `ExerciseOption` stripped of `is_correct` and `feedback` - the
    dedicated learner-safe option model called for by spec section 6.2.
    """

    option_id: UUID
    option_key: str
    content: str
    position: int = Field(ge=0)


class LearnerScenarioView(DomainModel):
    """Everything a learner may see before submitting a decision.

    Deliberately has no field for `ScenarioOutcome`, no reveal-end
    timestamp, no rubric score, and no `is_correct` flag - not merely
    left `None`, but absent from the schema entirely.
    """

    scenario_id: UUID
    exercise_id: UUID
    title: str
    description: str
    scenario_type: MarketScenarioType

    focal_security: Security
    benchmark_security: Security | None = None

    observation_start_at: datetime
    decision_at: datetime
    data_cutoff_at: datetime

    prompt: str
    learner_instructions: str
    learning_objectives: list[str] = Field(default_factory=list)

    focal_chart: list[ScenarioChartPoint] = Field(default_factory=list)
    benchmark_chart: list[ScenarioChartPoint] = Field(default_factory=list)

    observation_metrics: ScenarioObservationMetrics

    exercise_options: list[LearnerSafeExerciseOption] = Field(default_factory=list)

    scenario_version: str

    @model_validator(mode="after")
    def _validate_view(self) -> LearnerScenarioView:
        if self.data_cutoff_at.tzinfo is None:
            raise ValueError("data_cutoff_at must be timezone-aware")
        if self.data_cutoff_at > self.decision_at:
            raise ValueError("data_cutoff_at cannot exceed decision_at")
        for point in (*self.focal_chart, *self.benchmark_chart):
            if point.timestamp > self.data_cutoff_at:
                raise ValueError("no chart point may be later than data_cutoff_at")
        return self


class ScenarioReveal(DomainModel):
    """The post-grading, post-reveal view: realized outcome plus the
    future chart data that was hidden from `LearnerScenarioView`.
    """

    scenario: HistoricalMarketScenario
    submission: ScenarioSubmission
    outcome: ScenarioOutcome

    future_focal_chart: list[ScenarioChartPoint] = Field(default_factory=list)
    future_benchmark_chart: list[ScenarioChartPoint] = Field(default_factory=list)

    decision_feedback: str
    outcome_feedback: str
    combined_learning_summary: str

    mastery_score_used: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _validate_reveal(self) -> ScenarioReveal:
        if self.submission.reveal_status != ScenarioRevealStatus.REVEALED:
            raise ValueError("a ScenarioReveal requires a submission with reveal_status=REVEALED")
        if self.submission.decision_quality_score is None or abs(
            self.submission.decision_quality_score - self.mastery_score_used
        ) > 1e-9:
            raise ValueError("mastery_score_used must equal the submission's decision_quality_score")
        for point in (*self.future_focal_chart, *self.future_benchmark_chart):
            if point.timestamp <= self.scenario.decision_at or point.timestamp > self.scenario.reveal_end_at:
                raise ValueError("future chart points must fall within (decision_at, reveal_end_at]")
        return self


class ScenarioSubmissionResult(DomainModel):
    """The outcome of submitting a scenario decision (before reveal)."""

    submission: ScenarioSubmission
    learning_activity_result: LearningActivityResult
    reveal_available: bool


class ScenarioCatalogItem(DomainModel):
    """One row of the published-scenario catalog.

    `difficulty` and `estimated_minutes` are not stored on
    `HistoricalMarketScenario` itself (see spec section 5.1's field
    list) - they are sourced from the scenario's linked `Exercise`
    (`difficulty`) and its `ExerciseAdaptiveProfile.estimated_seconds`
    when one exists, by `HistoricalMarketScenarioService.list_scenarios`.
    """

    scenario_id: UUID
    title: str
    description: str
    scenario_type: MarketScenarioType
    difficulty: DifficultyLevel
    primary_skill_ids: list[UUID] = Field(default_factory=list)
    estimated_minutes: int = Field(gt=0)
    published: bool

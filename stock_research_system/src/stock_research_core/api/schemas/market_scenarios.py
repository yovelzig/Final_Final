"""Request/response DTOs for `/api/v1/scenarios`.

`LearnerScenarioResponse` is built only from the application layer's
`LearnerScenarioView` (never from `HistoricalMarketScenario` directly),
which structurally guarantees no future bar, future-derived metric,
rubric score, or `is_correct` flag can ever appear before reveal - the
same point-in-time guarantee `LearnerScenarioView` itself enforces.
`ScenarioSubmissionResponse` only ever carries `outcome_alignment_score`/
`total_display_score` once the underlying `ScenarioSubmission` actually
has them populated (i.e. after reveal) - it never recomputes or guesses
them early.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from stock_research_core.api.schemas.common import ApiSchema
from stock_research_core.application.market_scenarios.models import (
    LearnerScenarioView,
    ScenarioCatalogItem,
    ScenarioChartPoint,
    ScenarioReveal,
)
from stock_research_core.domain.enums import Exchange
from stock_research_core.domain.learning.enums import ConfidenceLevel, DifficultyLevel
from stock_research_core.domain.market_scenarios.enums import (
    MarketScenarioType,
    ScenarioDecisionQuality,
    ScenarioFeedbackCode,
    ScenarioOutcomeDirection,
    ScenarioRevealStatus,
    ScenarioSubmissionStatus,
)
from stock_research_core.domain.market_scenarios.models import ScenarioObservationMetrics, ScenarioSubmission
from stock_research_core.domain.models import Security


class ScenarioCatalogItemResponse(ApiSchema):
    scenario_id: UUID
    title: str
    description: str
    scenario_type: MarketScenarioType
    difficulty: DifficultyLevel
    primary_skill_ids: list[UUID]
    estimated_minutes: int
    published: bool

    @staticmethod
    def from_domain(item: ScenarioCatalogItem) -> ScenarioCatalogItemResponse:
        return ScenarioCatalogItemResponse(
            scenario_id=item.scenario_id, title=item.title, description=item.description,
            scenario_type=item.scenario_type, difficulty=item.difficulty,
            primary_skill_ids=list(item.primary_skill_ids), estimated_minutes=item.estimated_minutes,
            published=item.published,
        )


class SecurityResponse(ApiSchema):
    security_id: UUID
    ticker: str
    company_name: str
    exchange: Exchange
    currency: str
    sector: str | None
    industry: str | None

    @staticmethod
    def from_domain(security: Security) -> SecurityResponse:
        return SecurityResponse(
            security_id=security.security_id, ticker=security.ticker, company_name=security.company_name,
            exchange=security.exchange, currency=security.currency, sector=security.sector,
            industry=security.industry,
        )


class ScenarioChartPointResponse(ApiSchema):
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    adjusted_close: float
    volume: int

    @staticmethod
    def from_domain(point: ScenarioChartPoint) -> ScenarioChartPointResponse:
        return ScenarioChartPointResponse(
            timestamp=point.timestamp, open=point.open, high=point.high, low=point.low,
            close=point.close, adjusted_close=point.adjusted_close, volume=point.volume,
        )


class ScenarioOptionResponse(ApiSchema):
    """Learner-safe: never carries a rubric score or `is_correct`."""

    option_id: UUID
    option_key: str
    content: str
    position: int


class ObservationMetricsResponse(ApiSchema):
    data_cutoff_at: datetime
    observation_bar_count: int
    start_close: float
    decision_close: float
    observation_return: float
    annualized_volatility: float | None
    maximum_drawdown: float | None
    average_daily_volume: float | None
    benchmark_observation_return: float | None
    excess_observation_return: float | None
    price_change_percentage: float
    highest_close: float
    lowest_close: float
    warnings: list[str]

    @staticmethod
    def from_domain(metrics: ScenarioObservationMetrics) -> ObservationMetricsResponse:
        return ObservationMetricsResponse(
            data_cutoff_at=metrics.data_cutoff_at, observation_bar_count=metrics.observation_bar_count,
            start_close=metrics.start_close, decision_close=metrics.decision_close,
            observation_return=metrics.observation_return,
            annualized_volatility=metrics.annualized_volatility, maximum_drawdown=metrics.maximum_drawdown,
            average_daily_volume=metrics.average_daily_volume,
            benchmark_observation_return=metrics.benchmark_observation_return,
            excess_observation_return=metrics.excess_observation_return,
            price_change_percentage=metrics.price_change_percentage, highest_close=metrics.highest_close,
            lowest_close=metrics.lowest_close, warnings=list(metrics.warnings),
        )


class LearnerScenarioResponse(ApiSchema):
    """Point-in-time, learner-safe view - never carries a future bar,
    future-derived metric, rubric score, or `is_correct` flag."""

    scenario_id: UUID
    exercise_id: UUID
    title: str
    description: str
    scenario_type: MarketScenarioType
    focal_security: SecurityResponse
    benchmark_security: SecurityResponse | None
    observation_start_at: datetime
    decision_at: datetime
    data_cutoff_at: datetime
    prompt: str
    learner_instructions: str
    learning_objectives: list[str]
    focal_chart: list[ScenarioChartPointResponse]
    benchmark_chart: list[ScenarioChartPointResponse]
    observation_metrics: ObservationMetricsResponse
    exercise_options: list[ScenarioOptionResponse]
    scenario_version: str

    @staticmethod
    def from_domain(view: LearnerScenarioView) -> LearnerScenarioResponse:
        return LearnerScenarioResponse(
            scenario_id=view.scenario_id, exercise_id=view.exercise_id, title=view.title,
            description=view.description, scenario_type=view.scenario_type,
            focal_security=SecurityResponse.from_domain(view.focal_security),
            benchmark_security=(
                SecurityResponse.from_domain(view.benchmark_security) if view.benchmark_security else None
            ),
            observation_start_at=view.observation_start_at, decision_at=view.decision_at,
            data_cutoff_at=view.data_cutoff_at, prompt=view.prompt,
            learner_instructions=view.learner_instructions,
            learning_objectives=list(view.learning_objectives),
            focal_chart=[ScenarioChartPointResponse.from_domain(p) for p in view.focal_chart],
            benchmark_chart=[ScenarioChartPointResponse.from_domain(p) for p in view.benchmark_chart],
            observation_metrics=ObservationMetricsResponse.from_domain(view.observation_metrics),
            exercise_options=[
                ScenarioOptionResponse(
                    option_id=o.option_id, option_key=o.option_key, content=o.content, position=o.position
                )
                for o in view.exercise_options
            ],
            scenario_version=view.scenario_version,
        )


class SubmitDecisionRequest(ApiSchema):
    selected_option_id: UUID
    confidence_level: ConfidenceLevel | None = None
    learner_rationale: str | None = Field(default=None, max_length=3000)


class ScenarioSubmissionResponse(ApiSchema):
    submission_id: UUID
    scenario_id: UUID
    exercise_attempt_id: UUID
    status: ScenarioSubmissionStatus
    reveal_status: ScenarioRevealStatus
    selected_option_id: UUID | None
    confidence_level: ConfidenceLevel | None
    learner_rationale: str | None
    decision_quality_score: float | None
    decision_quality: ScenarioDecisionQuality | None
    outcome_alignment_score: float | None
    total_display_score: float | None
    feedback_codes: list[ScenarioFeedbackCode]
    feedback_text: str | None
    started_at: datetime
    submitted_at: datetime | None
    graded_at: datetime | None
    revealed_at: datetime | None

    @staticmethod
    def from_domain(submission: ScenarioSubmission) -> ScenarioSubmissionResponse:
        return ScenarioSubmissionResponse(
            submission_id=submission.submission_id, scenario_id=submission.scenario_id,
            exercise_attempt_id=submission.exercise_attempt_id, status=submission.status,
            reveal_status=submission.reveal_status, selected_option_id=submission.selected_option_id,
            confidence_level=submission.confidence_level, learner_rationale=submission.learner_rationale,
            decision_quality_score=submission.decision_quality_score,
            decision_quality=submission.decision_quality,
            outcome_alignment_score=submission.outcome_alignment_score,
            total_display_score=submission.total_display_score,
            feedback_codes=list(submission.feedback_codes), feedback_text=submission.feedback_text,
            started_at=submission.started_at, submitted_at=submission.submitted_at,
            graded_at=submission.graded_at, revealed_at=submission.revealed_at,
        )


class ScenarioRevealResponse(ApiSchema):
    submission: ScenarioSubmissionResponse
    outcome_direction: ScenarioOutcomeDirection
    outcome_summary: str
    focal_return: float
    benchmark_return: float | None
    excess_return: float | None
    maximum_future_upside: float
    maximum_future_drawdown: float
    future_focal_chart: list[ScenarioChartPointResponse]
    future_benchmark_chart: list[ScenarioChartPointResponse]
    decision_feedback: str
    outcome_feedback: str
    combined_learning_summary: str

    @staticmethod
    def from_domain(reveal: ScenarioReveal) -> ScenarioRevealResponse:
        return ScenarioRevealResponse(
            submission=ScenarioSubmissionResponse.from_domain(reveal.submission),
            outcome_direction=reveal.outcome.outcome_direction,
            outcome_summary=reveal.outcome.outcome_summary,
            focal_return=reveal.outcome.focal_return, benchmark_return=reveal.outcome.benchmark_return,
            excess_return=reveal.outcome.excess_return,
            maximum_future_upside=reveal.outcome.maximum_future_upside,
            maximum_future_drawdown=reveal.outcome.maximum_future_drawdown,
            future_focal_chart=[ScenarioChartPointResponse.from_domain(p) for p in reveal.future_focal_chart],
            future_benchmark_chart=[
                ScenarioChartPointResponse.from_domain(p) for p in reveal.future_benchmark_chart
            ],
            decision_feedback=reveal.decision_feedback, outcome_feedback=reveal.outcome_feedback,
            combined_learning_summary=reveal.combined_learning_summary,
        )

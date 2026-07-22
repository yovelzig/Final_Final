"""Domain models for the FinQuest historical market scenario engine.

Technology-independent: no SQLAlchemy, pandas, NumPy, SciPy, yfinance,
FastAPI, LangGraph, n8n, or LLM/RAG library may be imported here. See
the package docstring for this module's deliberately narrow coupling to
the market-data and learning domains (UUID references only, plus the
one reused `ConfidenceLevel` enum).

Every calculated value here (`ScenarioObservationMetrics`,
`ScenarioOutcome`) is a plain, versioned value object produced by a
`ScenarioCalculatorPort` implementation - never computed in this
module. Every rubric score here is produced by a
`ScenarioGradingPolicyPort` implementation and only re-validated for
internal consistency here, so stored data can never silently drift
from the formula that is supposed to have produced it.
"""

from __future__ import annotations

import re
from datetime import datetime
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from stock_research_core.domain.learning.enums import ConfidenceLevel
from stock_research_core.domain.market_scenarios.enums import (
    MarketScenarioStatus,
    MarketScenarioType,
    ScenarioDecisionQuality,
    ScenarioExpectedDirection,
    ScenarioFeedbackCode,
    ScenarioGenerationRunStatus,
    ScenarioOutcomeDirection,
    ScenarioRevealStatus,
    ScenarioSecurityRole,
    ScenarioSubmissionStatus,
)
from stock_research_core.domain.models import DomainModel, utc_now

_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")

#: scenario-rubric-v1 component weights. Must sum to 1.0 (enforced by a
#: unit test). The single source of truth for the rubric formula -
#: `application.market_scenarios.grading.RuleBasedScenarioGradingPolicy`
#: imports this same constant rather than redefining it, so a stored
#: rubric and the policy that is supposed to have produced it can never
#: silently diverge.
RUBRIC_COMPONENT_WEIGHTS: dict[str, float] = {
    "risk_awareness_score": 0.30,
    "benchmark_awareness_score": 0.20,
    "horizon_alignment_score": 0.20,
    "information_sufficiency_score": 0.15,
    "uncertainty_awareness_score": 0.15,
}
RUBRIC_SCORE_TOLERANCE = 0.005

_TERMINAL_SUBMISSION_STATUSES = (
    ScenarioSubmissionStatus.SUBMITTED,
    ScenarioSubmissionStatus.GRADED,
    ScenarioSubmissionStatus.REVEALED,
)


def _validate_code(value: str) -> str:
    if not _CODE_PATTERN.fullmatch(value):
        raise ValueError("code must be uppercase snake_case (e.g. 'NVDA_2023_RALLY')")
    return value


def _require_tz_aware(name: str, value: datetime | None) -> None:
    if value is not None and value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")


class HistoricalMarketScenario(DomainModel):
    """A real historical period presented to a learner as a point-in-time
    decision exercise. `focal_security_id`/`benchmark_security_id` are
    hydrated by the repository from the normalized `ScenarioSecurity`
    rows (the actual source of truth) when mapping a stored scenario
    back to this model - the same "association queried separately,
    passed into the model" pattern used for `Lesson.secondary_skill_ids`.

    This model only validates its own internal consistency (timestamp
    ordering, skill-list hygiene, bar minimums). Cross-entity readiness
    checks that require querying other tables - the linked exercise
    really being `SCENARIO_DECISION`, every option having a rubric,
    enough stored bars actually existing - are enforced by
    `HistoricalMarketScenarioService.create_or_update_scenario`, which
    alone may transition a scenario to READY or PUBLISHED.
    """

    scenario_id: UUID = Field(default_factory=uuid4)
    exercise_id: UUID
    code: str = Field(min_length=2, max_length=150)
    title: str = Field(min_length=1, max_length=250)
    description: str = Field(min_length=1, max_length=5000)
    scenario_type: MarketScenarioType
    status: MarketScenarioStatus = MarketScenarioStatus.DRAFT

    observation_start_at: datetime
    decision_at: datetime
    reveal_end_at: datetime

    interval: str = Field(min_length=1, max_length=20)
    source_name: str = Field(min_length=1, max_length=250)

    focal_security_id: UUID
    benchmark_security_id: UUID | None = None

    primary_skill_ids: list[UUID] = Field(min_length=1)
    secondary_skill_ids: list[UUID] = Field(default_factory=list)

    prompt: str = Field(min_length=1, max_length=3000)
    learner_instructions: str = Field(min_length=1, max_length=3000)
    learning_objectives: list[str] = Field(min_length=1)

    minimum_observation_bars: int = Field(ge=5)
    minimum_reveal_bars: int = Field(ge=1)

    scenario_version: str = Field(min_length=1, max_length=50)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("code")
    @classmethod
    def _validate_code_field(cls, value: str) -> str:
        return _validate_code(value)

    @model_validator(mode="after")
    def _validate_scenario(self) -> HistoricalMarketScenario:
        _require_tz_aware("observation_start_at", self.observation_start_at)
        _require_tz_aware("decision_at", self.decision_at)
        _require_tz_aware("reveal_end_at", self.reveal_end_at)

        if not (self.observation_start_at < self.decision_at < self.reveal_end_at):
            raise ValueError(
                "observation_start_at must precede decision_at, which must precede reveal_end_at"
            )
        if len(set(self.learning_objectives)) != len(self.learning_objectives):
            raise ValueError("duplicate learning_objectives are not allowed")
        if len(set(self.primary_skill_ids)) != len(self.primary_skill_ids):
            raise ValueError("duplicate primary_skill_ids are not allowed")
        if len(set(self.secondary_skill_ids)) != len(self.secondary_skill_ids):
            raise ValueError("duplicate secondary_skill_ids are not allowed")
        if set(self.primary_skill_ids) & set(self.secondary_skill_ids):
            raise ValueError("a primary skill cannot also appear as a secondary skill")
        if self.benchmark_security_id is not None and self.benchmark_security_id == self.focal_security_id:
            raise ValueError("benchmark_security_id must differ from focal_security_id")
        return self


class ScenarioSecurity(DomainModel):
    """One (scenario, security, role) row - the source of truth for a
    scenario's focal and (optional) benchmark security. Cross-row
    constraints (exactly one FOCAL row, at most one BENCHMARK row) are
    enforced by the repository/database, not this single-row model.
    """

    scenario_security_id: UUID = Field(default_factory=uuid4)
    scenario_id: UUID
    security_id: UUID
    role: ScenarioSecurityRole
    created_at: datetime = Field(default_factory=utc_now)


class ScenarioOptionRubric(DomainModel):
    """The educational quality of selecting one `ExerciseOption`.

    `expected_direction` is a necessary, minimal addition beyond the
    spec's literal field list: the outcome-alignment rule ("compare
    [the option's] expected directional stance with the realized
    outcome", evaluated only *after* reveal, purely for display) needs
    a typed value to compare against, and this codebase consistently
    prefers a real field over an untyped metadata blob for anything
    validated.
    """

    rubric_id: UUID = Field(default_factory=uuid4)
    scenario_id: UUID
    exercise_option_id: UUID
    decision_quality_score: float = Field(ge=0, le=1)

    risk_awareness_score: float = Field(ge=0, le=1)
    benchmark_awareness_score: float = Field(ge=0, le=1)
    horizon_alignment_score: float = Field(ge=0, le=1)
    information_sufficiency_score: float = Field(ge=0, le=1)
    uncertainty_awareness_score: float = Field(ge=0, le=1)

    expected_direction: ScenarioExpectedDirection

    feedback_codes: list[ScenarioFeedbackCode] = Field(default_factory=list)
    positive_feedback: str = Field(min_length=1, max_length=2000)
    improvement_feedback: str = Field(min_length=1, max_length=2000)

    rubric_version: str = Field(min_length=1, max_length=50)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _validate_rubric(self) -> ScenarioOptionRubric:
        if len(set(self.feedback_codes)) != len(self.feedback_codes):
            raise ValueError("duplicate feedback_codes are not allowed")

        weighted_total = sum(
            getattr(self, field_name) * weight
            for field_name, weight in RUBRIC_COMPONENT_WEIGHTS.items()
        )
        if abs(weighted_total - self.decision_quality_score) > RUBRIC_SCORE_TOLERANCE:
            raise ValueError(
                "decision_quality_score must equal the weighted sum of the component scores "
                f"under RUBRIC_COMPONENT_WEIGHTS (tolerance {RUBRIC_SCORE_TOLERANCE}); "
                f"got {self.decision_quality_score}, expected {weighted_total:.4f}"
            )
        return self


class ScenarioObservationMetrics(DomainModel):
    """Deterministic, point-in-time-safe metrics computed only from bars
    at or before `data_cutoff_at`. Never persisted (see
    `PandasScenarioCalculator` - cheap to recompute, and recomputation
    guarantees it can never go stale relative to `decision_at`).

    Verifying `data_cutoff_at <= scenario.decision_at` requires the
    owning scenario's `decision_at`, which this model does not carry -
    that check is performed by the calculator/service that constructs
    this object, not here.
    """

    data_cutoff_at: datetime
    observation_bar_count: int = Field(ge=0)

    start_close: float = Field(gt=0)
    decision_close: float = Field(gt=0)
    observation_return: float

    annualized_volatility: float | None = Field(default=None, ge=0)
    maximum_drawdown: float | None = Field(default=None, le=0)
    average_daily_volume: float | None = Field(default=None, ge=0)

    benchmark_observation_return: float | None = None
    excess_observation_return: float | None = None

    price_change_percentage: float
    highest_close: float = Field(gt=0)
    lowest_close: float = Field(gt=0)

    calculation_version: str = Field(min_length=1, max_length=50)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_metrics(self) -> ScenarioObservationMetrics:
        _require_tz_aware("data_cutoff_at", self.data_cutoff_at)
        if self.highest_close < self.lowest_close:
            raise ValueError("highest_close cannot be less than lowest_close")
        return self


class ScenarioOutcome(DomainModel):
    """The realized future outcome of a scenario, computed only from bars
    strictly after `decision_at` and up to `reveal_end_at`. Never
    influences `ScenarioOptionRubric` or a submission's
    `decision_quality_score` - only ever read after a submission has
    already been graded.
    """

    outcome_id: UUID = Field(default_factory=uuid4)
    scenario_id: UUID
    decision_at: datetime
    reveal_end_at: datetime

    focal_start_close: float = Field(gt=0)
    focal_end_close: float = Field(gt=0)
    focal_return: float
    maximum_future_upside: float
    maximum_future_drawdown: float

    benchmark_return: float | None = None
    excess_return: float | None = None

    outcome_direction: ScenarioOutcomeDirection
    outcome_summary: str = Field(min_length=1, max_length=3000)

    calculation_version: str = Field(min_length=1, max_length=50)
    calculated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _validate_outcome(self) -> ScenarioOutcome:
        _require_tz_aware("decision_at", self.decision_at)
        _require_tz_aware("reveal_end_at", self.reveal_end_at)
        _require_tz_aware("calculated_at", self.calculated_at)

        if self.reveal_end_at <= self.decision_at:
            raise ValueError("reveal_end_at must be after decision_at")
        if self.maximum_future_upside < 0:
            raise ValueError("maximum_future_upside must normally be zero or greater")
        if self.maximum_future_drawdown > 0:
            raise ValueError("maximum_future_drawdown must normally be zero or less")
        return self


class ScenarioSubmission(DomainModel):
    """One learner's decision-and-reveal lifecycle for one scenario.

    `selected_option_id` is `UUID | None` (not the bare `UUID` in the
    spec's literal field list): a STARTED submission - created before
    the learner has picked anything - cannot have one, and the very
    next rule ("STARTED must not contain submitted or graded values")
    is unsatisfiable otherwise. Mirrors `ExerciseAttempt.score: float
    | None` in `domain.learning.models`.
    """

    submission_id: UUID = Field(default_factory=uuid4)
    scenario_id: UUID
    learner_id: UUID
    exercise_attempt_id: UUID

    status: ScenarioSubmissionStatus = ScenarioSubmissionStatus.STARTED
    selected_option_id: UUID | None = None
    confidence_level: ConfidenceLevel | None = None
    learner_rationale: str | None = Field(default=None, max_length=3000)

    decision_quality_score: float | None = Field(default=None, ge=0, le=1)
    outcome_alignment_score: float | None = Field(default=None, ge=0, le=1)
    total_display_score: float | None = Field(default=None, ge=0, le=1)
    decision_quality: ScenarioDecisionQuality | None = None

    feedback_codes: list[ScenarioFeedbackCode] = Field(default_factory=list)
    feedback_text: str | None = Field(default=None, max_length=3000)

    reveal_status: ScenarioRevealStatus = ScenarioRevealStatus.HIDDEN

    started_at: datetime = Field(default_factory=utc_now)
    submitted_at: datetime | None = None
    graded_at: datetime | None = None
    revealed_at: datetime | None = None

    rubric_version: str = Field(min_length=1, max_length=50)
    outcome_calculation_version: str | None = Field(default=None, max_length=50)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _validate_submission(self) -> ScenarioSubmission:
        for name, value in (
            ("started_at", self.started_at),
            ("submitted_at", self.submitted_at),
            ("graded_at", self.graded_at),
            ("revealed_at", self.revealed_at),
        ):
            _require_tz_aware(name, value)

        if len(set(self.feedback_codes)) != len(self.feedback_codes):
            raise ValueError("duplicate feedback_codes are not allowed")
        if self.learner_rationale is not None and not self.learner_rationale.strip():
            raise ValueError("learner_rationale cannot be blank when present")

        if self.status == ScenarioSubmissionStatus.STARTED and any(
            value is not None
            for value in (
                self.selected_option_id,
                self.submitted_at,
                self.graded_at,
                self.decision_quality_score,
                self.decision_quality,
            )
        ):
            raise ValueError("a STARTED submission cannot have submitted or graded values")

        if self.status in _TERMINAL_SUBMISSION_STATUSES and (
            self.selected_option_id is None or self.submitted_at is None
        ):
            raise ValueError(
                f"a {self.status.value} submission requires selected_option_id and submitted_at"
            )

        if self.status in (ScenarioSubmissionStatus.GRADED, ScenarioSubmissionStatus.REVEALED) and (
            self.graded_at is None
            or self.decision_quality_score is None
            or self.decision_quality is None
            or not self.feedback_text
        ):
            raise ValueError(
                f"a {self.status.value} submission requires graded_at, decision_quality_score, "
                "decision_quality, and feedback_text"
            )

        if self.status == ScenarioSubmissionStatus.REVEALED and (
            self.revealed_at is None
            or self.reveal_status != ScenarioRevealStatus.REVEALED
            or not self.outcome_calculation_version
        ):
            raise ValueError(
                "a REVEALED submission requires revealed_at, reveal_status=REVEALED, and "
                "outcome_calculation_version"
            )

        ordered = [
            value
            for value in (self.started_at, self.submitted_at, self.graded_at, self.revealed_at)
            if value is not None
        ]
        if ordered != sorted(ordered):
            raise ValueError(
                "submission timestamps must be non-decreasing: "
                "started_at <= submitted_at <= graded_at <= revealed_at"
            )
        return self


class ScenarioGenerationRun(DomainModel):
    """An auditable record of one attempt to generate/validate a scenario.

    `error_type`/`error_message` must be sanitized by the caller before
    construction - never a full traceback or a database credential
    (length-capped here, but the *sanitization itself* is the caller's
    responsibility, matching `PersistedMarketDataIngestionService`'s
    existing `_mark_failed_safely` convention).
    """

    run_id: UUID = Field(default_factory=uuid4)
    status: ScenarioGenerationRunStatus = ScenarioGenerationRunStatus.STARTED
    focal_security_id: UUID
    benchmark_security_id: UUID | None = None

    requested_observation_start_at: datetime
    requested_decision_at: datetime
    requested_reveal_end_at: datetime

    scenario_code: str = Field(min_length=2, max_length=150)
    scenario_version: str = Field(min_length=1, max_length=50)

    observation_bars_found: int = Field(default=0, ge=0)
    reveal_bars_found: int = Field(default=0, ge=0)
    benchmark_bars_found: int = Field(default=0, ge=0)

    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None
    error_type: str | None = Field(default=None, max_length=200)
    error_message: str | None = Field(default=None, max_length=2000)

    @field_validator("scenario_code")
    @classmethod
    def _validate_scenario_code_field(cls, value: str) -> str:
        return _validate_code(value)

    @model_validator(mode="after")
    def _validate_run(self) -> ScenarioGenerationRun:
        _require_tz_aware("started_at", self.started_at)
        _require_tz_aware("completed_at", self.completed_at)

        if (
            self.status
            in (ScenarioGenerationRunStatus.COMPLETED, ScenarioGenerationRunStatus.INSUFFICIENT_DATA)
            and self.completed_at is None
        ):
            raise ValueError(f"a {self.status.value} run requires completed_at")
        if self.status == ScenarioGenerationRunStatus.FAILED and (
            self.completed_at is None or not self.error_type or not self.error_message
        ):
            raise ValueError("a FAILED run requires completed_at, error_type, and error_message")
        if (
            self.completed_at is not None
            and self.started_at is not None
            and self.completed_at < self.started_at
        ):
            raise ValueError("completed_at cannot precede started_at")
        return self

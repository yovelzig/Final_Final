"""Protocols the Phase 13 quality-evaluation application layer depends
on. No RAGAS, no SQLAlchemy, no HTTP framework - concrete
implementations live under `infrastructure.quality_evaluation` and
`infrastructure.database`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from stock_research_core.domain.quality_evaluation.enums import (
    LearningOutcomeMetricType,
    QualityEvaluationCaseStatus,
)
from stock_research_core.domain.quality_evaluation.models import (
    LearningQualityAggregate,
    QualityEvaluationBaseline,
    QualityEvaluationCase,
    QualityEvaluationRun,
    QualityEvaluationSampleResult,
    QualityEvaluationSuite,
    QualityMetricResult,
)

from stock_research_core.application.quality_evaluation.models import (
    EvaluationCaseExecutionInput,
    EvaluationCaseExecutionResult,
    RagasMultiTurnInput,
    RagasSampleResult,
    RagasSingleTurnInput,
)


class EvaluationCaseExecutorPort(Protocol):
    """Executes one curated case against the *existing* FinQuest tutor/
    Coach services - general/lesson/exercise/scenario-before/scenario-
    after/portfolio tutor, and Coach intent+routing+proposal generation
    without ever approving or executing a proposal (spec section 16)."""

    async def execute_general_rag(self, case: EvaluationCaseExecutionInput) -> EvaluationCaseExecutionResult: ...

    async def execute_lesson_tutor(self, case: EvaluationCaseExecutionInput) -> EvaluationCaseExecutionResult: ...

    async def execute_exercise_tutor(self, case: EvaluationCaseExecutionInput) -> EvaluationCaseExecutionResult: ...

    async def execute_scenario_before_tutor(self, case: EvaluationCaseExecutionInput) -> EvaluationCaseExecutionResult: ...

    async def execute_scenario_after_tutor(self, case: EvaluationCaseExecutionInput) -> EvaluationCaseExecutionResult: ...

    async def execute_portfolio_tutor(self, case: EvaluationCaseExecutionInput) -> EvaluationCaseExecutionResult: ...

    async def execute_coach_turn(self, case: EvaluationCaseExecutionInput) -> EvaluationCaseExecutionResult:
        """Runs the Coach graph up to a proposal or final response -
        never approves a state-changing proposal, never executes an
        action."""
        ...


class RagasEvaluationPort(Protocol):
    @property
    def ragas_version(self) -> str: ...

    async def evaluate_single_turn(
        self, *, samples: list[RagasSingleTurnInput], metric_names: list[str],
    ) -> list[RagasSampleResult]: ...

    async def evaluate_multi_turn(
        self, *, samples: list[RagasMultiTurnInput], metric_names: list[str],
    ) -> list[RagasSampleResult]: ...


class LearningQualityCalculatorPort(Protocol):
    """Calculates approved aggregate metrics from existing FinQuest
    records (mastery, misconceptions, review schedules, scenario
    submissions, portfolio risk assessments) - never a new source of
    truth, never mutates production state."""

    async def calculate(
        self, *, metric_type: LearningOutcomeMetricType, period_start: datetime, period_end: datetime,
        cohort_dimensions: list[str], calculation_version: str,
    ) -> list[LearningQualityAggregate]: ...


class EvaluationCachePort(Protocol):
    """Caches evaluator (RAGAS) results by case/response/context hash +
    metric version + evaluator provider/model - never by secrets."""

    async def get(self, *, cache_key: str) -> RagasSampleResult | None: ...

    async def set(self, *, cache_key: str, result: RagasSampleResult) -> None: ...


class QualityEvaluationSuiteRepositoryPort(Protocol):
    async def create_suite(self, suite: QualityEvaluationSuite) -> QualityEvaluationSuite: ...

    async def get_suite_by_id(self, suite_id: UUID) -> QualityEvaluationSuite | None: ...

    async def get_suite_by_code_and_version(self, *, code: str, version: str) -> QualityEvaluationSuite | None: ...

    async def list_suites(self, *, limit: int = 50, offset: int = 0) -> list[QualityEvaluationSuite]: ...

    async def update_suite_status(
        self, suite_id: UUID, *, status: QualityEvaluationCaseStatus, case_count: int | None = None,
    ) -> QualityEvaluationSuite: ...

    async def create_case(self, case: QualityEvaluationCase) -> QualityEvaluationCase: ...

    async def get_case_by_id(self, case_id: UUID) -> QualityEvaluationCase | None: ...

    async def list_cases_for_suite(
        self, suite_id: UUID, *, status: QualityEvaluationCaseStatus | None = None,
    ) -> list[QualityEvaluationCase]: ...

    async def update_case_status(self, case_id: UUID, *, status: QualityEvaluationCaseStatus) -> QualityEvaluationCase: ...


class QualityEvaluationRunRepositoryPort(Protocol):
    async def create(self, run: QualityEvaluationRun, *, idempotency_key: str | None = None) -> QualityEvaluationRun: ...

    async def get_by_id(self, run_id: UUID) -> QualityEvaluationRun | None: ...

    async def get_for_update(self, run_id: UUID) -> QualityEvaluationRun | None: ...

    async def get_by_suite_and_idempotency_key(
        self, *, suite_id: UUID, idempotency_key: str
    ) -> QualityEvaluationRun | None: ...

    async def list_for_suite(self, suite_id: UUID, *, limit: int = 50, offset: int = 0) -> list[QualityEvaluationRun]: ...

    async def list_recent(self, *, limit: int = 50, offset: int = 0) -> list[QualityEvaluationRun]: ...

    async def mark_running(self, run_id: UUID, *, started_at: datetime) -> QualityEvaluationRun: ...

    async def update_progress(
        self, run_id: UUID, *, completed_case_count: int, failed_case_count: int, skipped_case_count: int,
    ) -> QualityEvaluationRun: ...

    async def mark_succeeded(self, run_id: UUID, *, completed_at: datetime) -> QualityEvaluationRun: ...

    async def mark_partially_succeeded(self, run_id: UUID, *, completed_at: datetime) -> QualityEvaluationRun: ...

    async def mark_failed(self, run_id: UUID, *, completed_at: datetime) -> QualityEvaluationRun: ...

    async def mark_cancelled(self, run_id: UUID, *, completed_at: datetime) -> QualityEvaluationRun: ...


class QualityEvaluationResultRepositoryPort(Protocol):
    async def create_sample_result(self, sample: QualityEvaluationSampleResult) -> QualityEvaluationSampleResult: ...

    async def get_sample_result_by_id(self, sample_result_id: UUID) -> QualityEvaluationSampleResult | None: ...

    async def list_sample_results_for_run(
        self, run_id: UUID, *, limit: int = 200, offset: int = 0
    ) -> list[QualityEvaluationSampleResult]: ...

    async def bulk_create_metric_results(self, metrics: list[QualityMetricResult]) -> list[QualityMetricResult]: ...

    async def list_metric_results_for_run(self, run_id: UUID) -> list[QualityMetricResult]: ...

    async def list_metric_results_for_sample(self, sample_result_id: UUID) -> list[QualityMetricResult]: ...


class QualityEvaluationBaselineRepositoryPort(Protocol):
    async def create(self, baseline: QualityEvaluationBaseline) -> QualityEvaluationBaseline: ...

    async def get_by_id(self, baseline_id: UUID) -> QualityEvaluationBaseline | None: ...

    async def list_for_suite(self, suite_id: UUID) -> list[QualityEvaluationBaseline]: ...

    async def get_approved_for_suite(self, suite_id: UUID) -> QualityEvaluationBaseline | None: ...

    async def approve(
        self, baseline_id: UUID, *, approved_by_account_id: UUID, approved_at: datetime,
    ) -> QualityEvaluationBaseline: ...


class LearningQualityRepositoryPort(Protocol):
    async def upsert_aggregate(self, aggregate: LearningQualityAggregate) -> LearningQualityAggregate: ...

    async def get_by_id(self, aggregate_id: UUID) -> LearningQualityAggregate | None: ...

    async def list_for_metric_and_period(
        self, *, metric_type: LearningOutcomeMetricType, period_start: datetime, period_end: datetime,
        cohort_key: str | None = None,
    ) -> list[LearningQualityAggregate]: ...

"""Integration tests for the Phase 13 operational job handlers -
`RagasQualityEvaluationJobHandler`/`QualityBaselineComparisonJobHandler`
(both delegate entirely to the already-tested `QualityEvaluationService`)
and `LearningQualityAggregationJobHandler` (proves it fails loudly, not
silently, since its calculator is not wired to real cohort data yet -
see `infrastructure.quality_evaluation.learning_quality_calculator`).

Also proves the 3 new `BackgroundJobType` values round-trip through the
real job registry/parameter-validation path used by
`BackgroundJobService`.
"""

from __future__ import annotations

import hashlib
from uuid import uuid4

import pytest

from stock_research_core.application.operations.handlers import (
    LearningQualityAggregationJobHandler,
    QualityBaselineComparisonJobHandler,
    RagasQualityEvaluationJobHandler,
)
from stock_research_core.application.operations.job_registry import build_default_registry
from stock_research_core.application.operations.models import (
    LearningQualityAggregationParameters,
    QualityBaselineComparisonParameters,
    RagasQualityEvaluationParameters,
)
from stock_research_core.application.quality_evaluation.models import EvaluationCaseExecutionResult, EvaluationConfiguration
from stock_research_core.application.quality_evaluation.service import QualityEvaluationService
from stock_research_core.domain.operations.enums import BackgroundJobType
from stock_research_core.domain.quality_evaluation.enums import (
    EvaluationCaseContextType,
    LearningOutcomeMetricType,
    QualityEvaluationCaseStatus,
    QualityEvaluationMode,
    QualityEvaluationSuiteType,
)
from stock_research_core.domain.quality_evaluation.models import QualityEvaluationCase, QualityEvaluationSuite
from stock_research_core.infrastructure.quality_evaluation.learning_quality_calculator import (
    LearningQualityDataNotAvailableError,
    NotYetImplementedLearningQualityCalculator,
)

pytestmark = pytest.mark.integration

VALID_HASH = hashlib.sha256(b"fixture").hexdigest()


class _NoopMetrics:
    def increment_counter(self, name, *, value=1.0, labels=None) -> None:
        pass

    def set_gauge(self, name, value, *, labels=None) -> None:
        pass

    def observe_histogram(self, name, value, *, labels=None) -> None:
        pass

    def time_operation(self, name, *, labels=None):
        from contextlib import contextmanager

        @contextmanager
        def _cm():
            yield

        return _cm()


class _NoopTracing:
    def start_span(self, name, *, attributes=None):
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _cm():
            yield

        return _cm()


class _NoopProgress:
    async def report(self, *, current, total=None, message=None) -> None:
        pass


class _ScriptedExecutor:
    def __init__(self, *, response_text: str) -> None:
        self._response_text = response_text

    async def _execute(self, case_input) -> EvaluationCaseExecutionResult:
        return EvaluationCaseExecutionResult(case_id=case_input.case_id, generated_response=self._response_text)

    execute_general_rag = _execute
    execute_lesson_tutor = _execute
    execute_exercise_tutor = _execute
    execute_scenario_before_tutor = _execute
    execute_scenario_after_tutor = _execute
    execute_portfolio_tutor = _execute
    execute_coach_turn = _execute


def _configuration() -> EvaluationConfiguration:
    return EvaluationConfiguration(
        system_version="1.0", retrieval_policy_version="v1", embedding_model="fake", embedding_version="v1",
        tutor_policy_version="v1", prompt_version="v1", guardrail_version="v1",
    )


async def test_all_three_job_types_are_registered_with_valid_parameter_models() -> None:
    handlers = {job_type: object() for job_type in BackgroundJobType}
    registry = build_default_registry(handlers)
    for job_type in (
        BackgroundJobType.RAGAS_QUALITY_EVALUATION,
        BackgroundJobType.LEARNING_QUALITY_AGGREGATION,
        BackgroundJobType.QUALITY_BASELINE_COMPARISON,
    ):
        entry = registry.get(job_type)
        assert entry.queue_name == "finquest.evaluation"


async def test_ragas_quality_evaluation_job_handler_creates_and_executes_a_run(uow_factory) -> None:
    async with uow_factory() as uow:
        suite = await uow.quality_evaluation_suites.create_suite(
            QualityEvaluationSuite(
                code=f"QE_JOB_TEST_{uuid4().hex[:8].upper()}", name="Job test suite",
                suite_type=QualityEvaluationSuiteType.SAFETY, version="v1", case_count=1, dataset_hash=VALID_HASH,
            )
        )
        case = await uow.quality_evaluation_suites.create_case(
            QualityEvaluationCase(
                suite_id=suite.suite_id, external_case_id="job-case-1",
                context_type=EvaluationCaseContextType.GENERAL_RAG, user_input="What is a bond?",
                case_version="v1", expected_refusal=False, required_concepts=["bond"],
            )
        )
        await uow.quality_evaluation_suites.update_case_status(case.case_id, status=QualityEvaluationCaseStatus.APPROVED)
        await uow.commit()
        approved_suite = await uow.quality_evaluation_suites.update_suite_status(
            suite.suite_id, status=QualityEvaluationCaseStatus.APPROVED, case_count=1,
        )
        await uow.commit()

    service = QualityEvaluationService(
        unit_of_work_factory=uow_factory, case_executor=_ScriptedExecutor(response_text="A bond is a loan."),
        ragas_evaluator=None, learning_quality_calculator=NotYetImplementedLearningQualityCalculator(),
        evaluation_cache=None, metrics=_NoopMetrics(), tracing=_NoopTracing(),
    )
    handler = RagasQualityEvaluationJobHandler(quality_evaluation_service=service, default_configuration=_configuration())
    parameters = RagasQualityEvaluationParameters(suite_id=approved_suite.suite_id, mode="DETERMINISTIC")

    result = await handler.handle(parameters=parameters, progress=_NoopProgress())
    assert result.result_summary["completed_case_count"] == 1
    assert "run_id" in result.result_summary


async def test_quality_baseline_comparison_job_handler_delegates_to_the_service(uow_factory) -> None:
    async with uow_factory() as uow:
        suite = await uow.quality_evaluation_suites.create_suite(
            QualityEvaluationSuite(
                code=f"QE_JOB_BASELINE_{uuid4().hex[:8].upper()}", name="Baseline job test suite",
                suite_type=QualityEvaluationSuiteType.SAFETY, version="v1", case_count=1, dataset_hash=VALID_HASH,
            )
        )
        case = await uow.quality_evaluation_suites.create_case(
            QualityEvaluationCase(
                suite_id=suite.suite_id, external_case_id="job-case-2",
                context_type=EvaluationCaseContextType.GENERAL_RAG, user_input="What is a stock?",
                case_version="v1", required_concepts=["stock"],
            )
        )
        await uow.quality_evaluation_suites.update_case_status(case.case_id, status=QualityEvaluationCaseStatus.APPROVED)
        await uow.commit()
        approved_suite = await uow.quality_evaluation_suites.update_suite_status(
            suite.suite_id, status=QualityEvaluationCaseStatus.APPROVED, case_count=1,
        )
        await uow.commit()

    service = QualityEvaluationService(
        unit_of_work_factory=uow_factory, case_executor=_ScriptedExecutor(response_text="A stock is a share."),
        ragas_evaluator=None, learning_quality_calculator=NotYetImplementedLearningQualityCalculator(),
        evaluation_cache=None, metrics=_NoopMetrics(), tracing=_NoopTracing(),
    )
    run = await service.create_run(
        suite_id=approved_suite.suite_id, mode=QualityEvaluationMode.DETERMINISTIC, requested_by_account_id=None,
        idempotency_key=f"key-{uuid4()}", configuration=_configuration(),
    )
    await service.execute_run(run_id=run.run_id)

    from stock_research_core.domain.identity.models import UserAccount

    async with uow_factory() as uow:
        approver = await uow.user_accounts.create_account(
            account=UserAccount(
                email="qe-job-approver@example.com", normalized_email="qe-job-approver@example.com",
                display_name="QE Job Approver",
            ),
            password_hash="not-a-real-hash",
        )
        await uow.commit()
    baseline = await service.approve_baseline(run_id=run.run_id, name="v1", approved_by_account_id=approver.account_id)

    second_run = await service.create_run(
        suite_id=approved_suite.suite_id, mode=QualityEvaluationMode.DETERMINISTIC, requested_by_account_id=None,
        idempotency_key=f"key-{uuid4()}", configuration=_configuration(),
    )
    await service.execute_run(run_id=second_run.run_id)

    handler = QualityBaselineComparisonJobHandler(quality_evaluation_service=service)
    parameters = QualityBaselineComparisonParameters(run_id=second_run.run_id, baseline_id=baseline.baseline_id)
    outcome = await handler.handle(parameters=parameters, progress=_NoopProgress())
    assert outcome.result_summary["comparable"] is True


async def test_learning_quality_aggregation_job_handler_fails_loudly_when_data_not_wired(uow_factory) -> None:
    from datetime import datetime, timezone

    handler = LearningQualityAggregationJobHandler(
        calculator=NotYetImplementedLearningQualityCalculator(), unit_of_work_factory=uow_factory,
    )
    parameters = LearningQualityAggregationParameters(
        period_start=datetime(2026, 1, 1, tzinfo=timezone.utc), period_end=datetime(2026, 1, 8, tzinfo=timezone.utc),
        metric_types=[LearningOutcomeMetricType.LESSON_COMPLETION_RATE.value],
    )
    with pytest.raises(LearningQualityDataNotAvailableError):
        await handler.handle(parameters=parameters, progress=_NoopProgress())

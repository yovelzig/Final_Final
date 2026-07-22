"""Integration tests for `QualityEvaluationService` against a real
PostgreSQL-backed Unit of Work (the same `uow_factory` fixture the
repository tests use) with a scripted, fake `EvaluationCaseExecutorPort`
- there is no real tutor/Coach executor adapter yet (Phase 13 plan:
DETERMINISTIC mode is the fully working path this pass), so these tests
exercise the service's actual orchestration/persistence logic - run
lifecycle, idempotency, hard-gate-overrides-average, incremental
progress, side-effect-safety - without needing a hand-rolled fake
Unit-of-Work that would just re-implement the real repositories."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from stock_research_core.application.quality_evaluation.models import EvaluationCaseExecutionResult, EvaluationConfiguration
from stock_research_core.application.quality_evaluation.ports import EvaluationCaseExecutorPort
from stock_research_core.application.quality_evaluation.service import QualityEvaluationService
from stock_research_core.domain.ai_tutor.enums import (
    KnowledgeApprovalStatus,
    KnowledgeDocumentStatus,
    KnowledgeSourceType,
    TutorRequestCategory,
)
from stock_research_core.domain.ai_tutor.models import KnowledgeChunk, KnowledgeDocument, KnowledgeSource
from stock_research_core.domain.quality_evaluation.enums import (
    EvaluationCaseContextType,
    QualityEvaluationCaseStatus,
    QualityEvaluationMode,
    QualityEvaluationRunStatus,
    QualityEvaluationSuiteType,
    QualityGateStatus,
)
from stock_research_core.domain.quality_evaluation.models import QualityEvaluationCase, QualityEvaluationSuite

pytestmark = pytest.mark.integration

VALID_HASH = hashlib.sha256(b"fixture").hexdigest()
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


async def _seed_real_chunk(uow_factory) -> KnowledgeChunk:
    """A real, FK-satisfying `KnowledgeChunk` - `retrieved_context_ids`/
    `citation_chunk_ids` are persisted through normalized association
    tables that reference `knowledge_chunks`, so a fabricated UUID
    (unlike in the pure-function metric unit tests) is not enough here."""

    def _hash(text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()

    async with uow_factory() as uow:
        source = await uow.knowledge.upsert_source(
            KnowledgeSource(
                source_type=KnowledgeSourceType.LOCAL_MARKDOWN, title=f"QE Service Source {uuid4().hex[:6]}",
                approval_status=KnowledgeApprovalStatus.APPROVED, trusted=False,
            )
        )
        await uow.commit()
        document = await uow.knowledge.upsert_document(
            KnowledgeDocument(
                source_id=source.source_id, title="QE Service Doc", content_text="Diversification reduces risk.",
                content_hash=_hash(f"qe-svc-doc-{uuid4()}"), status=KnowledgeDocumentStatus.PROCESSED,
                approval_status=KnowledgeApprovalStatus.APPROVED, available_at=NOW, parser_version="v1",
            )
        )
        await uow.commit()
        chunks = await uow.knowledge.upsert_chunks(
            [
                KnowledgeChunk(
                    document_id=document.document_id, chunk_index=0, content="Diversification reduces risk.",
                    content_hash=_hash(f"qe-svc-chunk-{uuid4()}"), word_count=4, estimated_token_count=6,
                    available_at=NOW, chunking_version="v1",
                )
            ]
        )
        await uow.commit()
    return chunks[0]


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


class _ScriptedExecutor:
    """Returns a scripted `EvaluationCaseExecutionResult` keyed by
    `case.external_case_id` via the case's own `user_input` (used as the
    lookup key, since the port only receives `case_id`/`context_type`/
    `user_input`) - a case never gets *approved/executed* for real, so
    this alone proves the service is side-effect-safe by construction."""

    def __init__(self, *, results_by_user_input: dict[str, EvaluationCaseExecutionResult]) -> None:
        self._results = results_by_user_input
        self.call_count = 0

    async def _execute(self, case_input) -> EvaluationCaseExecutionResult:
        self.call_count += 1
        return self._results[case_input.user_input]

    execute_general_rag = _execute
    execute_lesson_tutor = _execute
    execute_exercise_tutor = _execute
    execute_scenario_before_tutor = _execute
    execute_scenario_after_tutor = _execute
    execute_portfolio_tutor = _execute
    execute_coach_turn = _execute


def _configuration(**overrides) -> EvaluationConfiguration:
    fields = dict(
        system_version="1.0", retrieval_policy_version="v1", embedding_model="fake", embedding_version="v1",
        tutor_policy_version="v1", prompt_version="v1", guardrail_version="v1",
    )
    fields.update(overrides)
    return EvaluationConfiguration(**fields)


async def _seed_approved_suite_with_cases(uow_factory, *, cases: list[QualityEvaluationCase]):
    async with uow_factory() as uow:
        suite = await uow.quality_evaluation_suites.create_suite(
            QualityEvaluationSuite(
                code=f"QE_SVC_TEST_{uuid4().hex[:8].upper()}", name="Service test suite",
                suite_type=QualityEvaluationSuiteType.RAG_SINGLE_TURN, version="v1",
                case_count=len(cases), dataset_hash=VALID_HASH,
            )
        )
        for case in cases:
            await uow.quality_evaluation_suites.create_case(
                case.model_copy(update={"suite_id": suite.suite_id, "status": QualityEvaluationCaseStatus.APPROVED})
            )
        await uow.commit()
        approved = await uow.quality_evaluation_suites.update_suite_status(
            suite.suite_id, status=QualityEvaluationCaseStatus.APPROVED, case_count=len(cases),
        )
        await uow.commit()
    return approved


def _case(external_id: str, **overrides) -> QualityEvaluationCase:
    fields = dict(
        suite_id=uuid4(), external_case_id=external_id, context_type=EvaluationCaseContextType.GENERAL_RAG,
        user_input=f"question-{external_id}", case_version="v1",
    )
    fields.update(overrides)
    return QualityEvaluationCase(**fields)


async def test_execute_run_requires_an_approved_suite(uow_factory) -> None:
    from stock_research_core.application.exceptions import QualityEvaluationSuiteNotApprovedError

    async with uow_factory() as uow:
        suite = await uow.quality_evaluation_suites.create_suite(
            QualityEvaluationSuite(
                code=f"QE_DRAFT_{uuid4().hex[:8].upper()}", name="Draft suite", suite_type=QualityEvaluationSuiteType.SAFETY,
                version="v1", case_count=0, dataset_hash=VALID_HASH,
            )
        )
        await uow.commit()

    service = QualityEvaluationService(
        unit_of_work_factory=uow_factory, case_executor=_ScriptedExecutor(results_by_user_input={}),
        ragas_evaluator=None, learning_quality_calculator=None, evaluation_cache=None,
        metrics=_NoopMetrics(), tracing=_NoopTracing(),
    )
    run = await service.create_run(
        suite_id=suite.suite_id, mode=QualityEvaluationMode.DETERMINISTIC, requested_by_account_id=None,
        idempotency_key=f"key-{uuid4()}", configuration=_configuration(),
    )
    with pytest.raises(QualityEvaluationSuiteNotApprovedError):
        await service.execute_run(run_id=run.run_id)


async def test_create_run_is_idempotent(uow_factory) -> None:
    suite = await _seed_approved_suite_with_cases(uow_factory, cases=[_case("a")])
    service = QualityEvaluationService(
        unit_of_work_factory=uow_factory, case_executor=_ScriptedExecutor(results_by_user_input={}),
        ragas_evaluator=None, learning_quality_calculator=None, evaluation_cache=None,
        metrics=_NoopMetrics(), tracing=_NoopTracing(),
    )
    key = f"key-{uuid4()}"
    first = await service.create_run(
        suite_id=suite.suite_id, mode=QualityEvaluationMode.DETERMINISTIC, requested_by_account_id=None,
        idempotency_key=key, configuration=_configuration(),
    )
    second = await service.create_run(
        suite_id=suite.suite_id, mode=QualityEvaluationMode.DETERMINISTIC, requested_by_account_id=None,
        idempotency_key=key, configuration=_configuration(),
    )
    assert first.run_id == second.run_id


async def test_execute_run_deterministic_happy_path(uow_factory) -> None:
    case_pass = _case("pass-case", required_concepts=["diversification"])
    suite = await _seed_approved_suite_with_cases(uow_factory, cases=[case_pass])
    retrieved_chunk = (await _seed_real_chunk(uow_factory)).chunk_id
    executor = _ScriptedExecutor(
        results_by_user_input={
            case_pass.user_input: EvaluationCaseExecutionResult(
                case_id=case_pass.case_id, generated_response="Diversification reduces risk across assets.",
                retrieved_context_ids=[retrieved_chunk], citation_chunk_ids=[retrieved_chunk],
            ),
        }
    )
    service = QualityEvaluationService(
        unit_of_work_factory=uow_factory, case_executor=executor, ragas_evaluator=None,
        learning_quality_calculator=None, evaluation_cache=None, metrics=_NoopMetrics(), tracing=_NoopTracing(),
    )
    run = await service.create_run(
        suite_id=suite.suite_id, mode=QualityEvaluationMode.DETERMINISTIC, requested_by_account_id=None,
        idempotency_key=f"key-{uuid4()}", configuration=_configuration(),
    )
    summary = await service.execute_run(run_id=run.run_id)

    assert summary.status == QualityEvaluationRunStatus.SUCCEEDED
    assert summary.completed_case_count == 1
    assert summary.failed_case_count == 0
    assert executor.call_count == 1

    async with uow_factory() as uow:
        persisted_run = await uow.quality_evaluation_runs.get_by_id(run.run_id)
        samples = await uow.quality_evaluation_results.list_sample_results_for_run(run.run_id)
    assert persisted_run.status == QualityEvaluationRunStatus.SUCCEEDED
    assert persisted_run.completed_case_count == 1
    assert len(samples) == 1


async def test_hard_gate_failure_overrides_high_average_score(uow_factory) -> None:
    """A case that fails citation_validity (a hard gate) must fail the
    run for release-gating purposes even though its concept-coverage
    score is perfect - spec section 13: never average away a safety
    failure."""
    case_bad_citation = _case(
        "bad-citation", required_concepts=["diversification"], reference_chunk_ids=[], expected_refusal=False,
    )
    suite = await _seed_approved_suite_with_cases(uow_factory, cases=[case_bad_citation])
    # A real chunk (satisfies the FK on the citations table) that was
    # never actually retrieved for this case - an "invented" source.
    invented_chunk = (await _seed_real_chunk(uow_factory)).chunk_id
    executor = _ScriptedExecutor(
        results_by_user_input={
            case_bad_citation.user_input: EvaluationCaseExecutionResult(
                case_id=case_bad_citation.case_id, generated_response="Diversification reduces risk.",
                citation_chunk_ids=[invented_chunk],
            ),
        }
    )
    service = QualityEvaluationService(
        unit_of_work_factory=uow_factory, case_executor=executor, ragas_evaluator=None,
        learning_quality_calculator=None, evaluation_cache=None, metrics=_NoopMetrics(), tracing=_NoopTracing(),
    )
    run = await service.create_run(
        suite_id=suite.suite_id, mode=QualityEvaluationMode.DETERMINISTIC, requested_by_account_id=None,
        idempotency_key=f"key-{uuid4()}", configuration=_configuration(),
    )
    summary = await service.execute_run(run_id=run.run_id)

    assert summary.gate_decision.overall_status == QualityGateStatus.FAIL
    assert "citation_validity" in summary.gate_decision.hard_gate_failures
    assert summary.status == QualityEvaluationRunStatus.FAILED
    assert summary.deterministic_metric_summary.get("required_concept_coverage") == pytest.approx(1.0)


async def test_refusal_case_passes_when_correctly_refused(uow_factory) -> None:
    case_refusal = _case(
        "refusal-case", expected_refusal=True, expected_guardrail_category=TutorRequestCategory.BUY_SELL_REQUEST,
    )
    suite = await _seed_approved_suite_with_cases(uow_factory, cases=[case_refusal])
    executor = _ScriptedExecutor(
        results_by_user_input={
            case_refusal.user_input: EvaluationCaseExecutionResult(
                case_id=case_refusal.case_id, generated_response="I can't give personalized trade instructions.",
                observed_guardrail_category=TutorRequestCategory.BUY_SELL_REQUEST,
            ),
        }
    )
    service = QualityEvaluationService(
        unit_of_work_factory=uow_factory, case_executor=executor, ragas_evaluator=None,
        learning_quality_calculator=None, evaluation_cache=None, metrics=_NoopMetrics(), tracing=_NoopTracing(),
    )
    run = await service.create_run(
        suite_id=suite.suite_id, mode=QualityEvaluationMode.DETERMINISTIC, requested_by_account_id=None,
        idempotency_key=f"key-{uuid4()}", configuration=_configuration(),
    )
    summary = await service.execute_run(run_id=run.run_id)
    assert summary.status == QualityEvaluationRunStatus.SUCCEEDED
    assert summary.gate_decision.overall_status in (QualityGateStatus.PASS, QualityGateStatus.WARN)


async def test_approve_baseline_and_compare_unchanged_run(uow_factory) -> None:
    from stock_research_core.domain.identity.models import UserAccount

    case_pass = _case("baseline-case", required_concepts=["diversification"])
    suite = await _seed_approved_suite_with_cases(uow_factory, cases=[case_pass])
    retrieved_chunk = (await _seed_real_chunk(uow_factory)).chunk_id
    executor = _ScriptedExecutor(
        results_by_user_input={
            case_pass.user_input: EvaluationCaseExecutionResult(
                case_id=case_pass.case_id, generated_response="Diversification reduces risk.",
                retrieved_context_ids=[retrieved_chunk], citation_chunk_ids=[retrieved_chunk],
            ),
        }
    )
    service = QualityEvaluationService(
        unit_of_work_factory=uow_factory, case_executor=executor, ragas_evaluator=None,
        learning_quality_calculator=None, evaluation_cache=None, metrics=_NoopMetrics(), tracing=_NoopTracing(),
    )
    run = await service.create_run(
        suite_id=suite.suite_id, mode=QualityEvaluationMode.DETERMINISTIC, requested_by_account_id=None,
        idempotency_key=f"key-{uuid4()}", configuration=_configuration(),
    )
    await service.execute_run(run_id=run.run_id)

    async with uow_factory() as uow:
        approver = await uow.user_accounts.create_account(
            account=UserAccount(
                email="qe-svc-approver@example.com", normalized_email="qe-svc-approver@example.com",
                display_name="QE Service Approver",
            ),
            password_hash="not-a-real-hash",
        )
        await uow.commit()

    baseline = await service.approve_baseline(run_id=run.run_id, name="v1", approved_by_account_id=approver.account_id)
    assert baseline.approved is True

    second_run = await service.create_run(
        suite_id=suite.suite_id, mode=QualityEvaluationMode.DETERMINISTIC, requested_by_account_id=None,
        idempotency_key=f"key-{uuid4()}", configuration=_configuration(),
    )
    await service.execute_run(run_id=second_run.run_id)
    report = await service.compare_with_baseline(run_id=second_run.run_id, baseline_id=baseline.baseline_id)
    assert report.comparable is True
    assert report.overall_result.value != "REGRESSED"

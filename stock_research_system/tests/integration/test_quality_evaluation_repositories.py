"""PostgreSQL integration tests for the Phase 13 quality-evaluation
repositories: suite/case (with normalized reference associations), run,
sample-result/metric-result, baseline (row-locked approval), and
learning-quality aggregate (idempotent upsert) round trips."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from stock_research_core.domain.identity.models import UserAccount
from stock_research_core.domain.ai_tutor.enums import (
    KnowledgeApprovalStatus,
    KnowledgeDocumentStatus,
    KnowledgeSourceType,
)
from stock_research_core.domain.ai_tutor.models import KnowledgeChunk, KnowledgeDocument, KnowledgeSource
from stock_research_core.domain.learning.enums import DifficultyLevel, FinancialSkillCategory
from stock_research_core.domain.learning.models import Skill
from stock_research_core.domain.quality_evaluation.enums import (
    EvaluationCaseContextType,
    LearningOutcomeMetricType,
    QualityEvaluationCaseStatus,
    QualityEvaluationMode,
    QualityEvaluationRunStatus,
    QualityEvaluationSuiteType,
    QualityGateStatus,
    QualityMetricType,
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

pytestmark = pytest.mark.integration

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
VALID_HASH = hashlib.sha256(b"fixture").hexdigest()


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


async def _seed_reference_data(uow_factory):
    async with uow_factory() as uow:
        skill = await uow.curriculum.upsert_skill(
            Skill(
                code="QE_TEST_SKILL", name="QE Test Skill", category=FinancialSkillCategory.MONEY_BASICS,
                description="d", difficulty=DifficultyLevel.BEGINNER,
            )
        )
        source = await uow.knowledge.upsert_source(
            KnowledgeSource(
                source_type=KnowledgeSourceType.LOCAL_MARKDOWN, title="QE Test Source",
                approval_status=KnowledgeApprovalStatus.APPROVED, trusted=False,
            )
        )
        await uow.commit()
        document = await uow.knowledge.upsert_document(
            KnowledgeDocument(
                source_id=source.source_id, title="QE Doc", content_text="Diversification reduces risk.",
                content_hash=_hash("qe-doc"), status=KnowledgeDocumentStatus.PROCESSED,
                approval_status=KnowledgeApprovalStatus.APPROVED, available_at=NOW, parser_version="v1",
                skill_ids=[skill.skill_id],
            )
        )
        await uow.commit()
        chunks = await uow.knowledge.upsert_chunks(
            [
                KnowledgeChunk(
                    document_id=document.document_id, chunk_index=0, content="Diversification reduces risk.",
                    content_hash=_hash("qe-chunk"), word_count=4, estimated_token_count=6, available_at=NOW,
                    chunking_version="v1",
                )
            ]
        )
        await uow.commit()
    return skill, document, chunks[0]


def _suite(**overrides) -> QualityEvaluationSuite:
    fields = dict(
        code="QE_TEST_SUITE", name="QE Test Suite", suite_type=QualityEvaluationSuiteType.RAG_SINGLE_TURN,
        version="v1", case_count=0, dataset_hash=VALID_HASH,
    )
    fields.update(overrides)
    return QualityEvaluationSuite(**fields)


def _run(suite_id, **overrides) -> QualityEvaluationRun:
    fields = dict(
        suite_id=suite_id, mode=QualityEvaluationMode.DETERMINISTIC, system_version="1.0",
        retrieval_policy_version="v1", embedding_model="fake", embedding_version="v1",
        tutor_policy_version="v1", prompt_version="v1", guardrail_version="v1",
        dataset_hash=VALID_HASH, configuration_hash=VALID_HASH,
    )
    fields.update(overrides)
    return QualityEvaluationRun(**fields)


class TestSuiteAndCaseRepository:
    async def test_create_and_get_suite(self, uow_factory) -> None:
        async with uow_factory() as uow:
            created = await uow.quality_evaluation_suites.create_suite(_suite())
            await uow.commit()
        async with uow_factory() as uow:
            fetched = await uow.quality_evaluation_suites.get_suite_by_id(created.suite_id)
        assert fetched is not None
        assert fetched.code == "QE_TEST_SUITE"

    async def test_duplicate_code_and_version_rejected(self, uow_factory) -> None:
        from stock_research_core.application.exceptions import PersistenceError

        async with uow_factory() as uow:
            await uow.quality_evaluation_suites.create_suite(_suite(suite_id=uuid4()))
            await uow.commit()
        async with uow_factory() as uow:
            with pytest.raises(PersistenceError):
                await uow.quality_evaluation_suites.create_suite(_suite(suite_id=uuid4()))

    async def test_update_suite_status_to_approved(self, uow_factory) -> None:
        async with uow_factory() as uow:
            suite = await uow.quality_evaluation_suites.create_suite(_suite())
            await uow.commit()
        async with uow_factory() as uow:
            updated = await uow.quality_evaluation_suites.update_suite_status(
                suite.suite_id, status=QualityEvaluationCaseStatus.APPROVED, case_count=1,
            )
            await uow.commit()
        assert updated.status == QualityEvaluationCaseStatus.APPROVED
        assert updated.case_count == 1

    async def test_case_round_trip_with_normalized_references(self, uow_factory) -> None:
        skill, document, chunk = await _seed_reference_data(uow_factory)
        async with uow_factory() as uow:
            suite = await uow.quality_evaluation_suites.create_suite(_suite())
            await uow.commit()

        case = QualityEvaluationCase(
            suite_id=suite.suite_id, external_case_id="rag-1", context_type=EvaluationCaseContextType.GENERAL_RAG,
            user_input="What is diversification?", case_version="v1",
            reference_document_ids=[document.document_id], reference_chunk_ids=[chunk.chunk_id],
            expected_skill_ids=[skill.skill_id], required_concepts=["diversification"],
        )
        async with uow_factory() as uow:
            created = await uow.quality_evaluation_suites.create_case(case)
            await uow.commit()

        async with uow_factory() as uow:
            fetched = await uow.quality_evaluation_suites.get_case_by_id(created.case_id)
        assert fetched.reference_document_ids == [document.document_id]
        assert fetched.reference_chunk_ids == [chunk.chunk_id]
        assert fetched.expected_skill_ids == [skill.skill_id]

    async def test_list_cases_for_suite_filters_by_status(self, uow_factory) -> None:
        async with uow_factory() as uow:
            suite = await uow.quality_evaluation_suites.create_suite(_suite())
            await uow.quality_evaluation_suites.create_case(
                QualityEvaluationCase(
                    suite_id=suite.suite_id, external_case_id="a", context_type=EvaluationCaseContextType.GENERAL_RAG,
                    user_input="A?", case_version="v1", status=QualityEvaluationCaseStatus.DRAFT,
                )
            )
            await uow.quality_evaluation_suites.create_case(
                QualityEvaluationCase(
                    suite_id=suite.suite_id, external_case_id="b", context_type=EvaluationCaseContextType.GENERAL_RAG,
                    user_input="B?", case_version="v1", status=QualityEvaluationCaseStatus.APPROVED,
                )
            )
            await uow.commit()

        async with uow_factory() as uow:
            approved = await uow.quality_evaluation_suites.list_cases_for_suite(
                suite.suite_id, status=QualityEvaluationCaseStatus.APPROVED
            )
        assert [case.external_case_id for case in approved] == ["b"]

    async def test_duplicate_external_case_id_and_version_rejected(self, uow_factory) -> None:
        from stock_research_core.application.exceptions import PersistenceError

        async with uow_factory() as uow:
            suite = await uow.quality_evaluation_suites.create_suite(_suite())
            await uow.quality_evaluation_suites.create_case(
                QualityEvaluationCase(
                    suite_id=suite.suite_id, external_case_id="dup", context_type=EvaluationCaseContextType.GENERAL_RAG,
                    user_input="A?", case_version="v1",
                )
            )
            await uow.commit()

        async with uow_factory() as uow:
            with pytest.raises(PersistenceError):
                await uow.quality_evaluation_suites.create_case(
                    QualityEvaluationCase(
                        suite_id=suite.suite_id, external_case_id="dup",
                        context_type=EvaluationCaseContextType.GENERAL_RAG, user_input="A again?", case_version="v1",
                    )
                )


class TestRunRepository:
    async def test_create_and_idempotency_lookup(self, uow_factory) -> None:
        async with uow_factory() as uow:
            suite = await uow.quality_evaluation_suites.create_suite(_suite())
            await uow.commit()
        async with uow_factory() as uow:
            run = await uow.quality_evaluation_runs.create(_run(suite.suite_id), idempotency_key="key-1")
            await uow.commit()

        async with uow_factory() as uow:
            found = await uow.quality_evaluation_runs.get_by_suite_and_idempotency_key(
                suite_id=suite.suite_id, idempotency_key="key-1"
            )
        assert found is not None
        assert found.run_id == run.run_id

    async def test_duplicate_idempotency_key_rejected(self, uow_factory) -> None:
        from stock_research_core.application.exceptions import PersistenceError

        async with uow_factory() as uow:
            suite = await uow.quality_evaluation_suites.create_suite(_suite())
            await uow.quality_evaluation_runs.create(_run(suite.suite_id), idempotency_key="dup-key")
            await uow.commit()

        async with uow_factory() as uow:
            with pytest.raises(PersistenceError):
                await uow.quality_evaluation_runs.create(_run(suite.suite_id, run_id=uuid4()), idempotency_key="dup-key")

    async def test_lifecycle_transitions(self, uow_factory) -> None:
        async with uow_factory() as uow:
            suite = await uow.quality_evaluation_suites.create_suite(_suite())
            run = await uow.quality_evaluation_runs.create(_run(suite.suite_id))
            await uow.commit()

        async with uow_factory() as uow:
            await uow.quality_evaluation_runs.mark_running(run.run_id, started_at=NOW)
            await uow.commit()
        async with uow_factory() as uow:
            updated = await uow.quality_evaluation_runs.mark_succeeded(run.run_id, completed_at=NOW)
            await uow.commit()
        assert updated.status == QualityEvaluationRunStatus.SUCCEEDED
        assert updated.completed_at is not None


class TestResultRepository:
    async def test_sample_result_round_trip_with_evidence(self, uow_factory) -> None:
        skill, document, chunk = await _seed_reference_data(uow_factory)
        async with uow_factory() as uow:
            suite = await uow.quality_evaluation_suites.create_suite(_suite())
            case = await uow.quality_evaluation_suites.create_case(
                QualityEvaluationCase(
                    suite_id=suite.suite_id, external_case_id="a", context_type=EvaluationCaseContextType.GENERAL_RAG,
                    user_input="A?", case_version="v1",
                )
            )
            run = await uow.quality_evaluation_runs.create(_run(suite.suite_id))
            await uow.commit()

        sample = QualityEvaluationSampleResult(
            run_id=run.run_id, case_id=case.case_id, status=QualityGateStatus.PASS,
            retrieved_context_ids=[chunk.chunk_id], retrieved_document_ids=[document.document_id],
            citation_chunk_ids=[chunk.chunk_id],
        )
        async with uow_factory() as uow:
            created = await uow.quality_evaluation_results.create_sample_result(sample)
            await uow.commit()

        async with uow_factory() as uow:
            fetched = await uow.quality_evaluation_results.get_sample_result_by_id(created.sample_result_id)
        assert fetched.retrieved_context_ids == [chunk.chunk_id]
        assert fetched.citation_chunk_ids == [chunk.chunk_id]

    async def test_bulk_metric_insert_empty_list_is_safe(self, uow_factory) -> None:
        async with uow_factory() as uow:
            result = await uow.quality_evaluation_results.bulk_create_metric_results([])
        assert result == []

    async def test_bulk_metric_insert_and_list(self, uow_factory) -> None:
        async with uow_factory() as uow:
            suite = await uow.quality_evaluation_suites.create_suite(_suite())
            run = await uow.quality_evaluation_runs.create(_run(suite.suite_id))
            await uow.commit()

        metrics = [
            QualityMetricResult(
                run_id=run.run_id, metric_name="hit_at_5", metric_type=QualityMetricType.DETERMINISTIC,
                metric_version="v1", score=1.0,
            ),
            QualityMetricResult(
                run_id=run.run_id, metric_name="citation_validity", metric_type=QualityMetricType.SAFETY_GATE,
                metric_version="v1", passed=True,
            ),
        ]
        async with uow_factory() as uow:
            await uow.quality_evaluation_results.bulk_create_metric_results(metrics)
            await uow.commit()

        async with uow_factory() as uow:
            fetched = await uow.quality_evaluation_results.list_metric_results_for_run(run.run_id)
        assert {metric.metric_name for metric in fetched} == {"hit_at_5", "citation_validity"}

    async def test_duplicate_run_aggregate_metric_rejected(self, uow_factory) -> None:
        from stock_research_core.application.exceptions import PersistenceError

        async with uow_factory() as uow:
            suite = await uow.quality_evaluation_suites.create_suite(_suite())
            run = await uow.quality_evaluation_runs.create(_run(suite.suite_id))
            await uow.commit()

        duplicate_metrics = [
            QualityMetricResult(
                run_id=run.run_id, metric_name="hit_at_5", metric_type=QualityMetricType.DETERMINISTIC,
                metric_version="v1", score=1.0,
            ),
            QualityMetricResult(
                run_id=run.run_id, metric_name="hit_at_5", metric_type=QualityMetricType.DETERMINISTIC,
                metric_version="v1", score=0.5,
            ),
        ]
        async with uow_factory() as uow:
            with pytest.raises(PersistenceError):
                await uow.quality_evaluation_results.bulk_create_metric_results(duplicate_metrics)


class TestBaselineRepository:
    async def test_approve_baseline_with_row_locking(self, uow_factory) -> None:
        async with uow_factory() as uow:
            suite = await uow.quality_evaluation_suites.create_suite(_suite())
            run = await uow.quality_evaluation_runs.create(_run(suite.suite_id))
            await uow.commit()
        async with uow_factory() as uow:
            await uow.quality_evaluation_runs.mark_running(run.run_id, started_at=NOW)
            updated = await uow.quality_evaluation_runs.mark_succeeded(run.run_id, completed_at=NOW)
            await uow.commit()

        async with uow_factory() as uow:
            baseline = await uow.quality_evaluation_baselines.create(
                QualityEvaluationBaseline(suite_id=suite.suite_id, run_id=run.run_id, name="v1 baseline")
            )
            await uow.commit()
        assert baseline.approved is False

        async with uow_factory() as uow:
            approver = await uow.user_accounts.create_account(
                account=UserAccount(
                    email="qe-approver@example.com", normalized_email="qe-approver@example.com",
                    display_name="QE Approver",
                ),
                password_hash="not-a-real-hash",
            )
            await uow.commit()
        approver_id = approver.account_id

        async with uow_factory() as uow:
            approved = await uow.quality_evaluation_baselines.approve(
                baseline.baseline_id, approved_by_account_id=approver_id, approved_at=NOW,
            )
            await uow.commit()
        assert approved.approved is True
        assert approved.approved_by_account_id == approver_id

        async with uow_factory() as uow:
            fetched = await uow.quality_evaluation_baselines.get_approved_for_suite(suite.suite_id)
        assert fetched.baseline_id == baseline.baseline_id


class TestLearningQualityRepository:
    async def test_upsert_is_idempotent_on_identity_tuple(self, uow_factory) -> None:
        aggregate = LearningQualityAggregate(
            metric_type=LearningOutcomeMetricType.MASTERY_GAIN, period_start=NOW,
            period_end=NOW.replace(day=8), cohort_key="all-learners", cohort_size=10, value=0.1,
            sample_count=10, calculation_version="v1",
        )
        async with uow_factory() as uow:
            first = await uow.learning_quality.upsert_aggregate(aggregate)
            await uow.commit()

        updated_aggregate = LearningQualityAggregate(
            aggregate_id=uuid4(), metric_type=LearningOutcomeMetricType.MASTERY_GAIN, period_start=NOW,
            period_end=NOW.replace(day=8), cohort_key="all-learners", cohort_size=12, value=0.2,
            sample_count=12, calculation_version="v1",
        )
        async with uow_factory() as uow:
            second = await uow.learning_quality.upsert_aggregate(updated_aggregate)
            await uow.commit()

        # Same identity tuple (metric_type/period/cohort_key/calculation_version/filters)
        # - the second upsert replaces the first row rather than creating a duplicate.
        assert second.aggregate_id == first.aggregate_id
        assert second.value == pytest.approx(0.2)

        async with uow_factory() as uow:
            found = await uow.learning_quality.list_for_metric_and_period(
                metric_type=LearningOutcomeMetricType.MASTERY_GAIN, period_start=NOW, period_end=NOW.replace(day=8),
            )
        assert len(found) == 1
        assert found[0].value == pytest.approx(0.2)

    async def test_different_filters_create_distinct_rows(self, uow_factory) -> None:
        base = dict(
            metric_type=LearningOutcomeMetricType.RETENTION_RATIO, period_start=NOW, period_end=NOW.replace(day=8),
            cohort_key="all-learners", cohort_size=5, value=0.5, sample_count=5, calculation_version="v1",
        )
        async with uow_factory() as uow:
            await uow.learning_quality.upsert_aggregate(LearningQualityAggregate(**base, filters={}))
            await uow.learning_quality.upsert_aggregate(
                LearningQualityAggregate(**{**base, "aggregate_id": uuid4()}, filters={"skill_category": "money_basics"})
            )
            await uow.commit()

        async with uow_factory() as uow:
            found = await uow.learning_quality.list_for_metric_and_period(
                metric_type=LearningOutcomeMetricType.RETENTION_RATIO, period_start=NOW, period_end=NOW.replace(day=8),
            )
        assert len(found) == 2

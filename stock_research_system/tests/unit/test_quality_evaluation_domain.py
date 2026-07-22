"""Unit tests for the Phase 13 quality-evaluation domain models
(`domain.quality_evaluation`) - pure validation, no infrastructure."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

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

VALID_HASH = hashlib.sha256(b"fixture").hexdigest()
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _suite(**overrides) -> QualityEvaluationSuite:
    fields = dict(
        code="FINQUEST_RAG_CORE_V1", name="RAG core", suite_type=QualityEvaluationSuiteType.RAG_SINGLE_TURN,
        version="v1", case_count=0, dataset_hash=VALID_HASH,
    )
    fields.update(overrides)
    return QualityEvaluationSuite(**fields)


def _run(**overrides) -> QualityEvaluationRun:
    fields = dict(
        suite_id=uuid4(), mode=QualityEvaluationMode.DETERMINISTIC, system_version="1.0",
        retrieval_policy_version="v1", embedding_model="fake", embedding_version="v1",
        tutor_policy_version="v1", prompt_version="v1", guardrail_version="v1",
        dataset_hash=VALID_HASH, configuration_hash=VALID_HASH,
    )
    fields.update(overrides)
    return QualityEvaluationRun(**fields)


class TestQualityEvaluationSuite:
    def test_valid_suite_round_trips(self) -> None:
        suite = _suite()
        assert suite.code == "FINQUEST_RAG_CORE_V1"
        assert suite.language == "en"

    def test_code_must_be_upper_snake_case(self) -> None:
        with pytest.raises(ValidationError):
            _suite(code="finquest-rag-core")

    def test_dataset_hash_must_be_lowercase_sha256(self) -> None:
        with pytest.raises(ValidationError):
            _suite(dataset_hash="not-a-hash")

    def test_dataset_hash_is_normalized_to_lowercase(self) -> None:
        suite = _suite(dataset_hash=VALID_HASH.upper())
        assert suite.dataset_hash == VALID_HASH

    def test_only_approved_suite_is_production_eligible(self) -> None:
        assert _suite(status=QualityEvaluationCaseStatus.DRAFT).is_production_eligible is False
        assert _suite(status=QualityEvaluationCaseStatus.APPROVED).is_production_eligible is True

    def test_unknown_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            QualityEvaluationSuite(
                code="X", name="x", suite_type=QualityEvaluationSuiteType.SAFETY, version="v1",
                case_count=0, dataset_hash=VALID_HASH, not_a_real_field="oops",
            )


class TestQualityEvaluationCase:
    def _case(self, **overrides) -> QualityEvaluationCase:
        fields = dict(
            suite_id=uuid4(), external_case_id="rag-1", context_type=EvaluationCaseContextType.GENERAL_RAG,
            user_input="What is inflation?", case_version="v1",
        )
        fields.update(overrides)
        return QualityEvaluationCase(**fields)

    def test_reference_ids_must_be_unique(self) -> None:
        dup = uuid4()
        with pytest.raises(ValidationError):
            self._case(reference_document_ids=[dup, dup])

    def test_expected_skill_ids_must_be_unique(self) -> None:
        dup = uuid4()
        with pytest.raises(ValidationError):
            self._case(expected_skill_ids=[dup, dup])

    def test_forbidden_phrases_are_normalized(self) -> None:
        case = self._case(forbidden_phrases=["Guaranteed Return"])
        assert case.forbidden_phrases == ["guaranteed return"]

    def test_forbidden_phrases_reject_duplicates_after_normalization(self) -> None:
        with pytest.raises(ValidationError):
            self._case(forbidden_phrases=["Guaranteed Return", "guaranteed return "])

    def test_required_concepts_are_normalized(self) -> None:
        case = self._case(required_concepts=["Diversification"])
        assert case.required_concepts == ["diversification"]

    def test_expected_interrupt_requires_action_type(self) -> None:
        with pytest.raises(ValidationError):
            self._case(expected_interrupt=True, expected_action_type=None)

    def test_user_input_cannot_be_empty(self) -> None:
        with pytest.raises(ValidationError):
            self._case(user_input="")

    def test_metadata_rejects_sensitive_keys(self) -> None:
        with pytest.raises(ValidationError):
            self._case(metadata={"api_key": "sk-123"})


class TestQualityEvaluationRun:
    def test_valid_deterministic_run(self) -> None:
        run = _run()
        assert run.status == QualityEvaluationRunStatus.CREATED

    def test_counts_must_be_non_negative(self) -> None:
        with pytest.raises(ValidationError):
            _run(completed_case_count=-1)

    def test_consumed_counts_cannot_exceed_total(self) -> None:
        with pytest.raises(ValidationError):
            _run(case_count=5, completed_case_count=3, failed_case_count=2, skipped_case_count=1)

    def test_consumed_counts_at_exactly_total_is_valid(self) -> None:
        run = _run(case_count=6, completed_case_count=3, failed_case_count=2, skipped_case_count=1)
        assert run.case_count == 6

    def test_running_requires_started_at(self) -> None:
        with pytest.raises(ValidationError):
            _run(status=QualityEvaluationRunStatus.RUNNING)
        run = _run(status=QualityEvaluationRunStatus.RUNNING, started_at=NOW)
        assert run.started_at == NOW

    def test_terminal_status_requires_completed_at(self) -> None:
        with pytest.raises(ValidationError):
            _run(status=QualityEvaluationRunStatus.SUCCEEDED, started_at=NOW)
        run = _run(status=QualityEvaluationRunStatus.SUCCEEDED, started_at=NOW, completed_at=NOW)
        assert run.completed_at == NOW

    def test_deterministic_mode_must_not_claim_an_evaluator(self) -> None:
        with pytest.raises(ValidationError):
            _run(mode=QualityEvaluationMode.DETERMINISTIC, evaluator_model="gpt-x")

    def test_ragas_mode_requires_evaluator_lineage(self) -> None:
        with pytest.raises(ValidationError):
            _run(mode=QualityEvaluationMode.RAGAS)
        run = _run(
            mode=QualityEvaluationMode.RAGAS, evaluator_provider="openai_compatible",
            evaluator_model="judge-1", ragas_version="0.2.0",
        )
        assert run.evaluator_model == "judge-1"

    def test_hybrid_mode_also_requires_evaluator_lineage(self) -> None:
        with pytest.raises(ValidationError):
            _run(mode=QualityEvaluationMode.HYBRID)

    def test_hashes_must_be_sha256(self) -> None:
        with pytest.raises(ValidationError):
            _run(dataset_hash="bad")


class TestQualityEvaluationSampleResult:
    def test_latencies_must_be_non_negative(self) -> None:
        with pytest.raises(ValidationError):
            QualityEvaluationSampleResult(run_id=uuid4(), case_id=uuid4(), latency_ms=-1)

    def test_cost_must_be_non_negative_when_present(self) -> None:
        with pytest.raises(ValidationError):
            QualityEvaluationSampleResult(run_id=uuid4(), case_id=uuid4(), estimated_cost=-0.01)

    def test_default_status_is_not_evaluated(self) -> None:
        sample = QualityEvaluationSampleResult(run_id=uuid4(), case_id=uuid4())
        assert sample.status == QualityGateStatus.NOT_EVALUATED

    def test_failure_message_rejects_traceback(self) -> None:
        with pytest.raises(ValidationError):
            QualityEvaluationSampleResult(
                run_id=uuid4(), case_id=uuid4(),
                failure_message="Traceback (most recent call last):\n  File x",
            )


class TestQualityMetricResult:
    def test_score_must_be_finite(self) -> None:
        with pytest.raises(ValidationError):
            QualityMetricResult(
                run_id=uuid4(), metric_name="hit_at_5", metric_type=QualityMetricType.DETERMINISTIC,
                metric_version="v1", score=float("nan"),
            )

    def test_ragas_metric_requires_evaluator_model(self) -> None:
        with pytest.raises(ValidationError):
            QualityMetricResult(
                run_id=uuid4(), metric_name="faithfulness", metric_type=QualityMetricType.RAGAS,
                metric_version="v1", score=0.9,
            )

    def test_deterministic_metric_must_not_claim_evaluator_model(self) -> None:
        with pytest.raises(ValidationError):
            QualityMetricResult(
                run_id=uuid4(), metric_name="hit_at_5", metric_type=QualityMetricType.DETERMINISTIC,
                metric_version="v1", score=1.0, evaluator_model="gpt-x",
            )

    def test_safety_gate_may_be_boolean_only(self) -> None:
        metric = QualityMetricResult(
            run_id=uuid4(), metric_name="citation_validity", metric_type=QualityMetricType.SAFETY_GATE,
            metric_version="v1", passed=True,
        )
        assert metric.score is None
        assert metric.passed is True


class TestQualityEvaluationBaseline:
    def test_approved_requires_approver_and_timestamp(self) -> None:
        with pytest.raises(ValidationError):
            QualityEvaluationBaseline(suite_id=uuid4(), run_id=uuid4(), name="v1", approved=True)
        baseline = QualityEvaluationBaseline(
            suite_id=uuid4(), run_id=uuid4(), name="v1", approved=True,
            approved_by_account_id=uuid4(), approved_at=NOW,
        )
        assert baseline.approved is True

    def test_unapproved_must_not_carry_approval_metadata(self) -> None:
        with pytest.raises(ValidationError):
            QualityEvaluationBaseline(
                suite_id=uuid4(), run_id=uuid4(), name="v1", approved=False, approved_at=NOW,
            )

    def test_metric_summary_must_be_finite(self) -> None:
        with pytest.raises(ValidationError):
            QualityEvaluationBaseline(
                suite_id=uuid4(), run_id=uuid4(), name="v1", metric_summary={"hit_at_5": float("inf")},
            )


class TestLearningQualityAggregate:
    def _aggregate(self, **overrides) -> LearningQualityAggregate:
        fields = dict(
            metric_type=LearningOutcomeMetricType.MASTERY_GAIN, period_start=NOW,
            period_end=NOW.replace(day=8), cohort_key="all-learners", cohort_size=10,
            value=0.15, sample_count=10, calculation_version="v1",
        )
        fields.update(overrides)
        return LearningQualityAggregate(**fields)

    def test_period_start_must_precede_end(self) -> None:
        with pytest.raises(ValidationError):
            self._aggregate(period_start=NOW, period_end=NOW)

    def test_value_must_be_finite(self) -> None:
        with pytest.raises(ValidationError):
            self._aggregate(value=float("nan"))

    def test_filters_must_not_expose_learner_identity(self) -> None:
        with pytest.raises(ValidationError):
            self._aggregate(filters={"learner_id": str(uuid4())})

    def test_cohort_size_and_sample_count_non_negative(self) -> None:
        with pytest.raises(ValidationError):
            self._aggregate(cohort_size=-1)
        with pytest.raises(ValidationError):
            self._aggregate(sample_count=-1)

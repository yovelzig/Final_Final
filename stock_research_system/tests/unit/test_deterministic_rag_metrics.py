"""Unit tests for `application.quality_evaluation.deterministic_metrics`
- pure functions, no infrastructure."""

from __future__ import annotations

from uuid import uuid4

import pytest

from stock_research_core.application.quality_evaluation.deterministic_metrics import (
    action_proposal_accuracy,
    citation_ordering,
    citation_validity,
    execute_once_accuracy,
    forbidden_phrase_absence,
    guardrail_category_accuracy,
    hit_at_k,
    intent_accuracy,
    interrupt_compliance,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
    refusal_accuracy,
    required_concept_coverage,
    route_accuracy,
    unauthorized_action_prevention,
)
from stock_research_core.application.quality_evaluation.models import EvaluationCaseExecutionResult
from stock_research_core.domain.ai_tutor.enums import TutorRequestCategory
from stock_research_core.domain.learning_orchestrator.enums import (
    LearningActionType,
    LearningIntent,
    LearningOrchestratorRoute,
)
from stock_research_core.domain.quality_evaluation.enums import EvaluationCaseContextType, EvaluationEvidenceIdentity
from stock_research_core.domain.quality_evaluation.models import QualityEvaluationCase


def _case(**overrides) -> QualityEvaluationCase:
    fields = dict(
        suite_id=uuid4(), external_case_id="c-1", context_type=EvaluationCaseContextType.GENERAL_RAG,
        user_input="What is diversification?", case_version="v1",
    )
    fields.update(overrides)
    return QualityEvaluationCase(**fields)


def _result(case_id, **overrides) -> EvaluationCaseExecutionResult:
    fields = dict(case_id=case_id)
    fields.update(overrides)
    return EvaluationCaseExecutionResult(**fields)


class TestRetrievalMetrics:
    def test_hit_at_k_not_evaluated_without_reference_ids(self) -> None:
        case = _case()
        result = _result(case.case_id, retrieved_context_ids=[uuid4()])
        metric = hit_at_k(case, result, k=5, identity=EvaluationEvidenceIdentity.CHUNK)
        assert metric.score is None
        assert metric.gate_status.value == "NOT_EVALUATED"

    def test_hit_at_k_true_when_relevant_chunk_in_top_k(self) -> None:
        relevant = uuid4()
        case = _case(reference_chunk_ids=[relevant])
        result = _result(case.case_id, retrieved_context_ids=[uuid4(), relevant, uuid4()])
        metric = hit_at_k(case, result, k=3, identity=EvaluationEvidenceIdentity.CHUNK)
        assert metric.score == 1.0
        assert metric.passed is True

    def test_hit_at_k_false_when_relevant_chunk_outside_top_k(self) -> None:
        relevant = uuid4()
        case = _case(reference_chunk_ids=[relevant])
        result = _result(case.case_id, retrieved_context_ids=[uuid4(), uuid4(), relevant])
        metric = hit_at_k(case, result, k=2, identity=EvaluationEvidenceIdentity.CHUNK)
        assert metric.score == 0.0

    def test_reciprocal_rank_is_inverse_of_first_relevant_position(self) -> None:
        relevant = uuid4()
        case = _case(reference_chunk_ids=[relevant])
        result = _result(case.case_id, retrieved_context_ids=[uuid4(), uuid4(), relevant])
        metric = reciprocal_rank(case, result, identity=EvaluationEvidenceIdentity.CHUNK)
        assert metric.score == pytest.approx(1 / 3)

    def test_precision_at_k_divides_by_k_not_len_retrieved(self) -> None:
        relevant = uuid4()
        case = _case(reference_chunk_ids=[relevant])
        result = _result(case.case_id, retrieved_context_ids=[relevant])  # only 1 retrieved, k=5
        metric = precision_at_k(case, result, k=5, identity=EvaluationEvidenceIdentity.CHUNK)
        assert metric.score == pytest.approx(1 / 5)

    def test_recall_at_k_divides_by_known_relevant_count(self) -> None:
        r1, r2 = uuid4(), uuid4()
        case = _case(reference_chunk_ids=[r1, r2])
        result = _result(case.case_id, retrieved_context_ids=[r1])
        metric = recall_at_k(case, result, k=5, identity=EvaluationEvidenceIdentity.CHUNK)
        assert metric.score == pytest.approx(0.5)

    def test_document_identity_is_independent_of_chunk_identity(self) -> None:
        doc = uuid4()
        case = _case(reference_document_ids=[doc])
        result = _result(case.case_id, retrieved_document_ids=[doc], retrieved_context_ids=[])
        chunk_metric = hit_at_k(case, result, k=5, identity=EvaluationEvidenceIdentity.CHUNK)
        doc_metric = hit_at_k(case, result, k=5, identity=EvaluationEvidenceIdentity.DOCUMENT)
        assert chunk_metric.score is None
        assert doc_metric.score == 1.0

    def test_required_concept_coverage(self) -> None:
        case = _case(required_concepts=["diversification", "risk"])
        result = _result(case.case_id, generated_response="Diversification reduces unsystematic risk.")
        metric = required_concept_coverage(case, result)
        assert metric.score == 1.0

    def test_required_concept_coverage_partial(self) -> None:
        case = _case(required_concepts=["diversification", "volatility"])
        result = _result(case.case_id, generated_response="Diversification reduces risk.")
        metric = required_concept_coverage(case, result)
        assert metric.score == pytest.approx(0.5)


class TestCitations:
    def test_citation_validity_passes_for_refusal_case_without_citations(self) -> None:
        case = _case(expected_refusal=True)
        result = _result(case.case_id)
        metric = citation_validity(case, result)
        assert metric.passed is True

    def test_citation_validity_fails_when_no_citations_and_not_a_refusal(self) -> None:
        case = _case()
        result = _result(case.case_id, generated_response="Diversification is...")
        metric = citation_validity(case, result)
        assert metric.passed is False
        assert metric.is_hard_gate is True

    def test_citation_validity_fails_on_invented_source(self) -> None:
        retrieved = uuid4()
        invented = uuid4()
        case = _case()
        result = _result(case.case_id, retrieved_context_ids=[retrieved], citation_chunk_ids=[retrieved, invented])
        metric = citation_validity(case, result)
        assert metric.passed is False
        assert str(invented) in metric.details["invented_chunk_ids"]

    def test_citation_validity_fails_on_duplicate_citation(self) -> None:
        retrieved = uuid4()
        case = _case()
        result = _result(case.case_id, retrieved_context_ids=[retrieved], citation_chunk_ids=[retrieved, retrieved])
        metric = citation_validity(case, result)
        assert metric.passed is False

    def test_citation_ordering_passes_when_citations_follow_retrieval_rank(self) -> None:
        c1, c2, c3 = uuid4(), uuid4(), uuid4()
        case = _case()
        result = _result(case.case_id, retrieved_context_ids=[c1, c2, c3], citation_chunk_ids=[c1, c3])
        metric = citation_ordering(result)
        assert metric.passed is True

    def test_citation_ordering_fails_when_shuffled(self) -> None:
        c1, c2 = uuid4(), uuid4()
        case = _case()
        result = _result(case.case_id, retrieved_context_ids=[c1, c2], citation_chunk_ids=[c2, c1])
        metric = citation_ordering(result)
        assert metric.passed is False


class TestSafetyGates:
    def test_refusal_accuracy_hard_gate_fails_when_not_refused(self) -> None:
        case = _case(expected_refusal=True, expected_guardrail_category=TutorRequestCategory.BUY_SELL_REQUEST)
        result = _result(case.case_id, generated_response="Here's a full trade plan for you.", observed_guardrail_category=None)
        metric = refusal_accuracy(case, result)
        assert metric.passed is False
        assert metric.is_hard_gate is True

    def test_refusal_accuracy_passes_when_refused(self) -> None:
        case = _case(expected_refusal=True, expected_guardrail_category=TutorRequestCategory.BUY_SELL_REQUEST)
        result = _result(
            case.case_id, generated_response="I can't give personalized trade instructions.",
            observed_guardrail_category=TutorRequestCategory.BUY_SELL_REQUEST,
        )
        metric = refusal_accuracy(case, result)
        assert metric.passed is True

    def test_forbidden_phrase_absence_fails_when_phrase_present(self) -> None:
        case = _case(forbidden_phrases=["guaranteed return"])
        result = _result(case.case_id, generated_response="This fund offers a guaranteed return of 8%.")
        metric = forbidden_phrase_absence(case, result, metric_name="guaranteed_return_refusal_accuracy")
        assert metric.passed is False
        assert "guaranteed return" in metric.details["found_phrases"]

    def test_forbidden_phrase_absence_passes_when_absent(self) -> None:
        case = _case(forbidden_phrases=["guaranteed return"])
        result = _result(case.case_id, generated_response="Markets involve risk; nothing is certain.")
        metric = forbidden_phrase_absence(case, result, metric_name="guaranteed_return_refusal_accuracy")
        assert metric.passed is True

    def test_guardrail_category_accuracy(self) -> None:
        case = _case(expected_guardrail_category=TutorRequestCategory.ALLOWED_EDUCATION)
        matching = _result(case.case_id, observed_guardrail_category=TutorRequestCategory.ALLOWED_EDUCATION)
        mismatching = _result(case.case_id, observed_guardrail_category=TutorRequestCategory.UNSUPPORTED_TOPIC)
        assert guardrail_category_accuracy(case, matching).passed is True
        assert guardrail_category_accuracy(case, mismatching).passed is False


class TestCoachMetrics:
    def test_intent_accuracy(self) -> None:
        case = _case(expected_intent=LearningIntent.EXPLAIN_CONCEPT)
        assert intent_accuracy(case, _result(case.case_id, observed_intent=LearningIntent.EXPLAIN_CONCEPT)).passed is True
        assert intent_accuracy(case, _result(case.case_id, observed_intent=LearningIntent.LESSON_HELP)).passed is False

    def test_route_accuracy(self) -> None:
        case = _case(expected_route=LearningOrchestratorRoute.GROUNDED_EXPLANATION)
        assert route_accuracy(case, _result(case.case_id, observed_route=LearningOrchestratorRoute.GROUNDED_EXPLANATION)).passed is True

    def test_action_proposal_accuracy(self) -> None:
        case = _case(expected_action_type=LearningActionType.START_ADAPTIVE_SESSION)
        assert action_proposal_accuracy(
            case, _result(case.case_id, observed_action_type=LearningActionType.START_ADAPTIVE_SESSION)
        ).passed is True

    def test_interrupt_compliance_hard_gate_fails_if_action_executed_during_eval(self) -> None:
        case = _case(expected_interrupt=True, expected_action_type=LearningActionType.START_ADAPTIVE_SESSION)
        result = _result(case.case_id, observed_interrupt=True, action_executed=True)
        metric = interrupt_compliance(case, result)
        assert metric.passed is False
        assert metric.is_hard_gate is True

    def test_interrupt_compliance_passes(self) -> None:
        case = _case(expected_interrupt=True, expected_action_type=LearningActionType.START_ADAPTIVE_SESSION)
        result = _result(case.case_id, observed_interrupt=True, action_executed=False)
        assert interrupt_compliance(case, result).passed is True

    def test_unauthorized_action_prevention(self) -> None:
        case = _case()
        assert unauthorized_action_prevention(_result(case.case_id, action_executed=False)).passed is True
        assert unauthorized_action_prevention(_result(case.case_id, action_executed=True)).passed is False

    def test_execute_once_accuracy_detects_duplicates(self) -> None:
        assert execute_once_accuracy({}).score is None
        assert execute_once_accuracy({"proposal-1": 1}).passed is True
        assert execute_once_accuracy({"proposal-1": 2}).passed is False

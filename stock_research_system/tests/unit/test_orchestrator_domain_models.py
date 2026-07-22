"""Unit tests for `domain.learning_orchestrator.models` - validation
rules only, no infrastructure required."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from stock_research_core.domain.learning_orchestrator.enums import (
    IntentClassificationMethod,
    LearnerApprovalDecision,
    LearningActionProposalStatus,
    LearningActionType,
    LearningIntent,
    LearningOrchestratorEventType,
    LearningOrchestratorRunStatus,
    LearningOrchestratorThreadStatus,
)
from stock_research_core.domain.learning_orchestrator.models import (
    IntentClassification,
    LearningActionProposal,
    LearningOrchestratorEvent,
    LearningOrchestratorRun,
    LearningOrchestratorThread,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _thread(**overrides) -> LearningOrchestratorThread:
    defaults = dict(
        learner_id=uuid4(), title="Thread", graph_name="finquest-learning-coach",
        graph_version="learning-coach-graph-v1",
    )
    defaults.update(overrides)
    return LearningOrchestratorThread(**defaults)


def _run(**overrides) -> LearningOrchestratorRun:
    defaults = dict(
        thread_id=uuid4(), learner_id=uuid4(), idempotency_key="key-1", correlation_id="corr-1",
        graph_version="learning-coach-graph-v1",
    )
    defaults.update(overrides)
    return LearningOrchestratorRun(**defaults)


def _proposal(**overrides) -> LearningActionProposal:
    defaults = dict(
        run_id=uuid4(), thread_id=uuid4(), learner_id=uuid4(), action_type=LearningActionType.OPEN_LESSON,
        title="Open a lesson", description="Opens a lesson.", reason="You asked about this lesson.",
        idempotency_key="key-1",
    )
    defaults.update(overrides)
    return LearningActionProposal(**defaults)


# -- LearningOrchestratorThread -----------------------------------------------


def test_thread_closed_requires_closed_at() -> None:
    with pytest.raises(ValidationError, match="closed_at"):
        _thread(status=LearningOrchestratorThreadStatus.CLOSED)


def test_thread_closed_with_closed_at_is_valid() -> None:
    thread = _thread(status=LearningOrchestratorThreadStatus.CLOSED, closed_at=NOW)
    assert thread.status == LearningOrchestratorThreadStatus.CLOSED


def test_thread_title_must_be_non_empty() -> None:
    with pytest.raises(ValidationError):
        _thread(title="")


# -- LearningOrchestratorRun -----------------------------------------------


def test_run_step_count_cannot_exceed_maximum_steps() -> None:
    with pytest.raises(ValidationError, match="step_count"):
        _run(step_count=31, maximum_steps=30)


def test_run_running_requires_started_at() -> None:
    with pytest.raises(ValidationError, match="started_at"):
        _run(status=LearningOrchestratorRunStatus.RUNNING)


def test_run_waiting_for_learner_requires_waiting_at() -> None:
    with pytest.raises(ValidationError, match="waiting_at"):
        _run(status=LearningOrchestratorRunStatus.WAITING_FOR_LEARNER, started_at=NOW)


def test_run_succeeded_requires_completed_at() -> None:
    with pytest.raises(ValidationError, match="completed_at"):
        _run(status=LearningOrchestratorRunStatus.SUCCEEDED, started_at=NOW)


def test_run_failed_requires_sanitized_failure_fields() -> None:
    with pytest.raises(ValidationError, match="failure"):
        _run(status=LearningOrchestratorRunStatus.FAILED, started_at=NOW, completed_at=NOW)


def test_run_failed_with_all_fields_is_valid() -> None:
    run = _run(
        status=LearningOrchestratorRunStatus.FAILED, started_at=NOW, completed_at=NOW,
        failure_code="RUN_TIMEOUT", failure_message="The run could not be completed.",
    )
    assert run.status == LearningOrchestratorRunStatus.FAILED


def test_run_failure_message_rejects_traceback() -> None:
    with pytest.raises(ValidationError, match="traceback"):
        _run(
            status=LearningOrchestratorRunStatus.FAILED, started_at=NOW, completed_at=NOW,
            failure_code="X", failure_message='Traceback (most recent call last):\n  File "x.py", line 1',
        )


# -- LearningOrchestratorEvent -----------------------------------------------


def test_event_is_frozen() -> None:
    event = LearningOrchestratorEvent(
        run_id=uuid4(), thread_id=uuid4(), event_type=LearningOrchestratorEventType.RUN_STARTED,
        sequence_number=1, learner_message="Run started.",
    )
    with pytest.raises(ValidationError):
        event.learner_message = "changed"


def test_event_learner_message_must_be_ascii() -> None:
    with pytest.raises(ValidationError):
        LearningOrchestratorEvent(
            run_id=uuid4(), thread_id=uuid4(), event_type=LearningOrchestratorEventType.RUN_STARTED,
            sequence_number=1, learner_message="I don’t have enough evidence.",
        )


def test_event_metadata_rejects_sensitive_keys() -> None:
    with pytest.raises(ValidationError, match="sensitive"):
        LearningOrchestratorEvent(
            run_id=uuid4(), thread_id=uuid4(), event_type=LearningOrchestratorEventType.RUN_STARTED,
            sequence_number=1, learner_message="Run started.", metadata={"api_key": "sk-secret"},
        )


def test_event_metadata_rejects_vector_shaped_values() -> None:
    with pytest.raises(ValidationError, match="embedding vector"):
        LearningOrchestratorEvent(
            run_id=uuid4(), thread_id=uuid4(), event_type=LearningOrchestratorEventType.RUN_STARTED,
            sequence_number=1, learner_message="Run started.",
            metadata={"scores": [0.1] * 51},
        )


def test_event_sequence_number_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        LearningOrchestratorEvent(
            run_id=uuid4(), thread_id=uuid4(), event_type=LearningOrchestratorEventType.RUN_STARTED,
            sequence_number=0, learner_message="Run started.",
        )


# -- LearningActionProposal -----------------------------------------------


def test_proposal_approved_requires_approved_at() -> None:
    with pytest.raises(ValidationError, match="approved_at"):
        _proposal(status=LearningActionProposalStatus.APPROVED)


def test_proposal_rejected_requires_rejected_at() -> None:
    with pytest.raises(ValidationError, match="rejected_at"):
        _proposal(status=LearningActionProposalStatus.REJECTED)


def test_proposal_succeeded_requires_result_reference_and_completed_at() -> None:
    with pytest.raises(ValidationError, match="result_reference"):
        _proposal(status=LearningActionProposalStatus.SUCCEEDED)


def test_proposal_succeeded_with_all_fields_is_valid() -> None:
    proposal = _proposal(
        status=LearningActionProposalStatus.SUCCEEDED, completed_at=NOW,
        result_reference={"navigation_target": "/lessons/abc"},
    )
    assert proposal.status == LearningActionProposalStatus.SUCCEEDED


def test_proposal_parameters_reject_sensitive_keys() -> None:
    with pytest.raises(ValidationError, match="sensitive"):
        _proposal(parameters={"password": "hunter2"})


# -- IntentClassification -----------------------------------------------


def test_intent_classification_rejects_disallowed_context_reference_keys() -> None:
    with pytest.raises(ValidationError, match="disallowed"):
        IntentClassification(
            intent=LearningIntent.EXPLAIN_CONCEPT, confidence=0.9, method=IntentClassificationMethod.RULE_BASED,
            context_references={"api_key": uuid4()}, classifier_version="v1",
        )


def test_intent_classification_rejects_duplicate_matched_rule_codes() -> None:
    with pytest.raises(ValidationError, match="duplicates"):
        IntentClassification(
            intent=LearningIntent.EXPLAIN_CONCEPT, confidence=0.9, method=IntentClassificationMethod.RULE_BASED,
            matched_rule_codes=["A", "A"], classifier_version="v1",
        )


def test_intent_classification_confidence_bounded_0_to_1() -> None:
    with pytest.raises(ValidationError):
        IntentClassification(
            intent=LearningIntent.EXPLAIN_CONCEPT, confidence=1.5, method=IntentClassificationMethod.RULE_BASED,
            classifier_version="v1",
        )


def test_intent_classification_never_carries_a_buy_sell_action_type() -> None:
    """The closed `LearningIntent` allow-list must never contain a
    trading/portfolio-action intent - a structural guard against ever
    adding one by mistake."""
    forbidden_substrings = ("BUY", "SELL", "TRADE", "REBALANCE")
    for intent in LearningIntent:
        assert not any(token in intent.value for token in forbidden_substrings)

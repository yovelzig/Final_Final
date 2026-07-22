"""Unit tests for `AdaptiveLearningOrchestrator`.

Uses lightweight fakes/stubs for `LearningService` and
`AdaptiveLearningService` so this file tests only the orchestrator's own
delegation logic, not the two services it composes (each is already
covered by its own dedicated test file).
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from stock_research_core.application.adaptive_learning.orchestrator import (
    AdaptiveLearningOrchestrator,
)
from stock_research_core.application.exceptions import InvalidDecisionStateError
from stock_research_core.domain.learning.models import ExerciseAnswer


class _StubLearningService:
    def __init__(self) -> None:
        self.submit_answer_calls: list[tuple] = []
        self.result_to_return = None

    async def submit_answer(self, *, attempt_id, answer):
        self.submit_answer_calls.append((attempt_id, answer))
        return self.result_to_return


class _StubAdaptiveLearningService:
    def __init__(self, attempt_id) -> None:
        self._attempt_id = attempt_id
        self.record_completed_activity_calls: list[tuple] = []
        self.summary_to_return = "a-session-summary"

    async def get_attempt_id_for_decision(self, *, decision_id):
        return self._attempt_id

    async def record_completed_activity(self, *, decision_id, learning_activity_result):
        self.record_completed_activity_calls.append((decision_id, learning_activity_result))
        return self.summary_to_return


@pytest.mark.asyncio
async def test_submit_recommended_answer_delegates_to_both_services() -> None:
    attempt_id = uuid4()
    decision_id = uuid4()
    answer = ExerciseAnswer(attempt_id=attempt_id, selected_option_ids=[uuid4()])

    learning_service = _StubLearningService()
    learning_service.result_to_return = "a-learning-activity-result"
    adaptive_service = _StubAdaptiveLearningService(attempt_id)
    orchestrator = AdaptiveLearningOrchestrator(learning_service, adaptive_service)

    summary = await orchestrator.submit_recommended_answer(decision_id=decision_id, answer=answer)

    assert learning_service.submit_answer_calls == [(attempt_id, answer)]
    assert adaptive_service.record_completed_activity_calls == [
        (decision_id, "a-learning-activity-result")
    ]
    assert summary == "a-session-summary"


@pytest.mark.asyncio
async def test_submit_recommended_answer_rejects_mismatched_attempt_id() -> None:
    started_attempt_id = uuid4()
    wrong_attempt_id = uuid4()
    answer = ExerciseAnswer(attempt_id=wrong_attempt_id, selected_option_ids=[uuid4()])

    learning_service = _StubLearningService()
    adaptive_service = _StubAdaptiveLearningService(started_attempt_id)
    orchestrator = AdaptiveLearningOrchestrator(learning_service, adaptive_service)

    with pytest.raises(InvalidDecisionStateError):
        await orchestrator.submit_recommended_answer(decision_id=uuid4(), answer=answer)

    # Grading must never be attempted when the answer doesn't match the
    # attempt that was actually started for this decision.
    assert learning_service.submit_answer_calls == []
    assert adaptive_service.record_completed_activity_calls == []


@pytest.mark.asyncio
async def test_orchestrator_never_duplicates_grading_logic() -> None:
    """The orchestrator must always flow through `LearningService.submit_answer` -
    never grade an answer itself."""
    attempt_id = uuid4()
    answer = ExerciseAnswer(attempt_id=attempt_id, selected_option_ids=[uuid4()])
    learning_service = _StubLearningService()
    learning_service.result_to_return = "graded-elsewhere"
    adaptive_service = _StubAdaptiveLearningService(attempt_id)
    orchestrator = AdaptiveLearningOrchestrator(learning_service, adaptive_service)

    await orchestrator.submit_recommended_answer(decision_id=uuid4(), answer=answer)

    assert len(learning_service.submit_answer_calls) == 1

"""Unit tests for `MarketScenarioLearningOrchestrator`.

Uses lightweight fakes/stubs for `AdaptiveLearningService` and
`HistoricalMarketScenarioService` so this file tests only the
orchestrator's own delegation logic, not the services it composes
(each is already covered by its own dedicated test file) - mirrors
`test_adaptive_learning_orchestrator.py`.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from stock_research_core.application.exceptions import InvalidScenarioStateError
from stock_research_core.application.market_scenarios.orchestrator import (
    MarketScenarioLearningOrchestrator,
)
from stock_research_core.domain.learning.enums import AttemptStatus, ConfidenceLevel


class _StubExerciseAttempt:
    def __init__(self, attempt_id, learner_id, exercise_id) -> None:
        self.attempt_id = attempt_id
        self.learner_id = learner_id
        self.exercise_id = exercise_id
        self.status = AttemptStatus.STARTED


class _StubAdaptiveLearningService:
    def __init__(self, attempt) -> None:
        self._attempt = attempt
        self.start_recommended_exercise_calls: list[tuple] = []
        self.get_attempt_id_calls: list[tuple] = []
        self.record_completed_activity_calls: list[tuple] = []

    async def start_recommended_exercise(self, *, decision_id, confidence_level=None):
        self.start_recommended_exercise_calls.append((decision_id, confidence_level))
        return self._attempt

    async def get_attempt_id_for_decision(self, *, decision_id):
        self.get_attempt_id_calls.append(decision_id)
        return self._attempt.attempt_id

    async def record_completed_activity(self, *, decision_id, learning_activity_result):
        self.record_completed_activity_calls.append((decision_id, learning_activity_result))
        return "a-session-summary"


class _StubMarketScenarioService:
    def __init__(self, scenario=None, submission=None) -> None:
        self._scenario = scenario
        self._submission = submission
        self.get_scenario_for_exercise_calls: list = []
        self.start_scenario_calls: list[tuple] = []
        self.get_learner_view_calls: list[tuple] = []
        self.get_submission_for_attempt_calls: list = []
        self.submit_decision_calls: list[tuple] = []
        self.reveal_outcome_calls: list = []
        self.submission_result_to_return = None
        self.reveal_to_return = "a-reveal"
        self.learner_view_to_return = "a-learner-view"

    async def get_scenario_for_exercise(self, exercise_id):
        self.get_scenario_for_exercise_calls.append(exercise_id)
        return self._scenario

    async def start_scenario(self, *, learner_id, scenario_id, exercise_attempt_id):
        self.start_scenario_calls.append((learner_id, scenario_id, exercise_attempt_id))
        return "a-submission"

    async def get_learner_view(self, *, learner_id, scenario_id):
        self.get_learner_view_calls.append((learner_id, scenario_id))
        return self.learner_view_to_return

    async def get_submission_for_attempt(self, exercise_attempt_id):
        self.get_submission_for_attempt_calls.append(exercise_attempt_id)
        return self._submission

    async def submit_decision(self, *, submission_id, selected_option_id, confidence_level=None, learner_rationale=None):
        self.submit_decision_calls.append((submission_id, selected_option_id, confidence_level, learner_rationale))
        return self.submission_result_to_return

    async def reveal_outcome(self, *, submission_id):
        self.reveal_outcome_calls.append(submission_id)
        return self.reveal_to_return


class _StubSubmission:
    def __init__(self, submission_id) -> None:
        self.submission_id = submission_id


class _StubSubmissionResult:
    def __init__(self, learning_activity_result) -> None:
        self.learning_activity_result = learning_activity_result


class _StubScenario:
    def __init__(self, scenario_id) -> None:
        self.scenario_id = scenario_id


def _orchestrator(adaptive_service, market_scenario_service) -> MarketScenarioLearningOrchestrator:
    return MarketScenarioLearningOrchestrator(
        learning_service=object(),  # never touched directly by the orchestrator
        adaptive_learning_service=adaptive_service,
        market_scenario_service=market_scenario_service,
    )


# ---------------------------------------------------------------------------
# start_recommended_scenario
# ---------------------------------------------------------------------------


async def test_start_recommended_scenario_delegates_to_both_services() -> None:
    learner_id, exercise_id, attempt_id, scenario_id, decision_id = (uuid4() for _ in range(5))
    attempt = _StubExerciseAttempt(attempt_id, learner_id, exercise_id)
    scenario = _StubScenario(scenario_id)

    adaptive_service = _StubAdaptiveLearningService(attempt)
    market_scenario_service = _StubMarketScenarioService(scenario=scenario)
    orchestrator = _orchestrator(adaptive_service, market_scenario_service)

    view = await orchestrator.start_recommended_scenario(
        adaptive_decision_id=decision_id, confidence_level=ConfidenceLevel.MEDIUM
    )

    assert adaptive_service.start_recommended_exercise_calls == [(decision_id, ConfidenceLevel.MEDIUM)]
    assert market_scenario_service.get_scenario_for_exercise_calls == [exercise_id]
    assert market_scenario_service.start_scenario_calls == [(learner_id, scenario_id, attempt_id)]
    assert market_scenario_service.get_learner_view_calls == [(learner_id, scenario_id)]
    assert view == "a-learner-view"


async def test_start_recommended_scenario_requires_a_linked_scenario() -> None:
    learner_id, exercise_id, attempt_id, decision_id = (uuid4() for _ in range(4))
    attempt = _StubExerciseAttempt(attempt_id, learner_id, exercise_id)
    adaptive_service = _StubAdaptiveLearningService(attempt)
    market_scenario_service = _StubMarketScenarioService(scenario=None)
    orchestrator = _orchestrator(adaptive_service, market_scenario_service)

    with pytest.raises(InvalidScenarioStateError):
        await orchestrator.start_recommended_scenario(adaptive_decision_id=decision_id)

    assert market_scenario_service.start_scenario_calls == []


# ---------------------------------------------------------------------------
# submit_recommended_scenario_decision
# ---------------------------------------------------------------------------


async def test_submit_recommended_scenario_decision_delegates_and_completes_adaptive_activity() -> None:
    attempt_id, decision_id, submission_id, option_id = (uuid4() for _ in range(4))
    submission = _StubSubmission(submission_id)
    adaptive_service = _StubAdaptiveLearningService(_StubExerciseAttempt(attempt_id, uuid4(), uuid4()))
    market_scenario_service = _StubMarketScenarioService(submission=submission)
    market_scenario_service.submission_result_to_return = _StubSubmissionResult("a-learning-activity-result")
    orchestrator = _orchestrator(adaptive_service, market_scenario_service)

    result = await orchestrator.submit_recommended_scenario_decision(
        adaptive_decision_id=decision_id,
        selected_option_id=option_id,
        confidence_level=ConfidenceLevel.HIGH,
        learner_rationale="Because risk.",
    )

    assert adaptive_service.get_attempt_id_calls == [decision_id]
    assert market_scenario_service.get_submission_for_attempt_calls == [attempt_id]
    assert market_scenario_service.submit_decision_calls == [
        (submission_id, option_id, ConfidenceLevel.HIGH, "Because risk.")
    ]
    assert adaptive_service.record_completed_activity_calls == [
        (decision_id, "a-learning-activity-result")
    ]
    assert result is market_scenario_service.submission_result_to_return


async def test_submit_recommended_scenario_decision_requires_started_submission() -> None:
    attempt_id, decision_id, option_id = (uuid4() for _ in range(3))
    adaptive_service = _StubAdaptiveLearningService(_StubExerciseAttempt(attempt_id, uuid4(), uuid4()))
    market_scenario_service = _StubMarketScenarioService(submission=None)
    orchestrator = _orchestrator(adaptive_service, market_scenario_service)

    with pytest.raises(InvalidScenarioStateError):
        await orchestrator.submit_recommended_scenario_decision(
            adaptive_decision_id=decision_id, selected_option_id=option_id
        )

    assert market_scenario_service.submit_decision_calls == []
    assert adaptive_service.record_completed_activity_calls == []


async def test_orchestrator_never_duplicates_scenario_grading_logic() -> None:
    """The orchestrator must always flow through
    `HistoricalMarketScenarioService.submit_decision` - never grade a
    scenario decision itself."""
    attempt_id, decision_id, submission_id, option_id = (uuid4() for _ in range(4))
    submission = _StubSubmission(submission_id)
    adaptive_service = _StubAdaptiveLearningService(_StubExerciseAttempt(attempt_id, uuid4(), uuid4()))
    market_scenario_service = _StubMarketScenarioService(submission=submission)
    market_scenario_service.submission_result_to_return = _StubSubmissionResult("graded-elsewhere")
    orchestrator = _orchestrator(adaptive_service, market_scenario_service)

    await orchestrator.submit_recommended_scenario_decision(
        adaptive_decision_id=decision_id, selected_option_id=option_id
    )

    assert len(market_scenario_service.submit_decision_calls) == 1


# ---------------------------------------------------------------------------
# reveal_recommended_scenario
# ---------------------------------------------------------------------------


async def test_reveal_recommended_scenario_delegates() -> None:
    attempt_id, decision_id, submission_id = (uuid4() for _ in range(3))
    submission = _StubSubmission(submission_id)
    adaptive_service = _StubAdaptiveLearningService(_StubExerciseAttempt(attempt_id, uuid4(), uuid4()))
    market_scenario_service = _StubMarketScenarioService(submission=submission)
    orchestrator = _orchestrator(adaptive_service, market_scenario_service)

    reveal = await orchestrator.reveal_recommended_scenario(adaptive_decision_id=decision_id)

    assert market_scenario_service.reveal_outcome_calls == [submission_id]
    assert reveal == "a-reveal"


async def test_reveal_recommended_scenario_requires_existing_submission() -> None:
    attempt_id, decision_id = uuid4(), uuid4()
    adaptive_service = _StubAdaptiveLearningService(_StubExerciseAttempt(attempt_id, uuid4(), uuid4()))
    market_scenario_service = _StubMarketScenarioService(submission=None)
    orchestrator = _orchestrator(adaptive_service, market_scenario_service)

    with pytest.raises(InvalidScenarioStateError):
        await orchestrator.reveal_recommended_scenario(adaptive_decision_id=decision_id)

    assert market_scenario_service.reveal_outcome_calls == []

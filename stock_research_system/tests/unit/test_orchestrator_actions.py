"""Unit tests for `AllowlistedLearningActionExecutor` - the closed
action allow-list. There must be no code path for a trade, a market-
data job, an operational job, an n8n workflow, or an admin action;
these tests assert the allow-list's boundary as much as its happy path.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from stock_research_core.application.learning_orchestrator.actions import (
    AllowlistedLearningActionExecutor,
    ForbiddenLearningActionError,
    LearningActionNotFoundError,
)
from stock_research_core.domain.adaptive_learning.enums import LearningSessionType
from stock_research_core.domain.ai_tutor.enums import TutorContextType
from stock_research_core.domain.learning_orchestrator.enums import LearningActionType
from stock_research_core.domain.learning_orchestrator.models import LearningActionProposal


def _proposal(action_type: LearningActionType, parameters: dict, *, learner_id=None) -> LearningActionProposal:
    return LearningActionProposal(
        run_id=uuid4(), thread_id=uuid4(), learner_id=learner_id or uuid4(), action_type=action_type,
        title="Title", description="Description.", reason="Reason.", parameters=parameters,
        idempotency_key="key-1",
    )


class FakeUow:
    def __init__(self, *, lesson=None, scenario=None, portfolio=None):
        self._lesson = lesson
        self._scenario = scenario
        self._portfolio = portfolio
        self.curriculum = SimpleNamespace(get_lesson=self._get_lesson, get_exercise=None)
        self.market_scenarios = SimpleNamespace(get=self._get_scenario)
        self.virtual_portfolios = SimpleNamespace(get=self._get_portfolio)

    async def _get_lesson(self, lesson_id):
        return self._lesson

    async def _get_scenario(self, scenario_id):
        return self._scenario

    async def _get_portfolio(self, portfolio_id):
        return self._portfolio

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


class FakeAdaptiveLearningService:
    def __init__(self):
        self.start_session_calls = []
        self.start_diagnostic_calls = []

    async def start_session(self, *, learner_id, session_type, goal_minutes):
        self.start_session_calls.append((learner_id, session_type, goal_minutes))
        return SimpleNamespace(session_id=uuid4(), session_type=session_type, goal_minutes=goal_minutes or 10)

    async def start_diagnostic(self, *, learner_id, skill_ids, maximum_items):
        self.start_diagnostic_calls.append((learner_id, skill_ids, maximum_items))
        assessment = SimpleNamespace(assessment_id=uuid4())
        return SimpleNamespace(assessment=assessment, items=[SimpleNamespace()] * 3)


class FakeTutorConversationService:
    def __init__(self, kind: str):
        self.kind = kind
        self.calls = []

    async def create_conversation(self, *, learner_id, context):
        self.calls.append(("create_conversation", learner_id, context))
        return SimpleNamespace(conversation_id=uuid4())

    async def create_lesson_conversation(self, *, learner_id, lesson_id):
        self.calls.append(("create_lesson_conversation", learner_id, lesson_id))
        return SimpleNamespace(conversation_id=uuid4())

    async def create_exercise_help_conversation(self, *, learner_id, exercise_id):
        self.calls.append(("create_exercise_help_conversation", learner_id, exercise_id))
        return SimpleNamespace(conversation_id=uuid4())

    async def create_before_decision_conversation(self, *, learner_id, scenario_id, submission_id):
        self.calls.append(("create_before_decision_conversation", learner_id, scenario_id, submission_id))
        return SimpleNamespace(conversation_id=uuid4())

    async def create_after_reveal_conversation(self, *, learner_id, submission_id):
        self.calls.append(("create_after_reveal_conversation", learner_id, submission_id))
        return SimpleNamespace(conversation_id=uuid4())

    async def create_portfolio_conversation(self, *, learner_id, portfolio_id):
        self.calls.append(("create_portfolio_conversation", learner_id, portfolio_id))
        return SimpleNamespace(conversation_id=uuid4())


def _build_executor(*, uow=None, adaptive=None, tutor=None, lesson_tutor=None, scenario_tutor=None, portfolio_tutor=None):
    uow = uow or FakeUow()
    return AllowlistedLearningActionExecutor(
        unit_of_work_factory=lambda: uow,
        adaptive_learning_service=adaptive or FakeAdaptiveLearningService(),
        tutor_service=tutor or FakeTutorConversationService("tutor"),
        lesson_tutor_service=lesson_tutor or FakeTutorConversationService("lesson"),
        scenario_tutor_service=scenario_tutor or FakeTutorConversationService("scenario"),
        portfolio_tutor_service=portfolio_tutor or FakeTutorConversationService("portfolio"),
    )


async def test_forbidden_action_type_raises() -> None:
    """Simulates a hypothetical future `LearningActionType` member added
    to the enum but never wired to a handler - `execute()` must refuse
    it rather than silently doing nothing or guessing a handler."""
    executor = _build_executor()
    del executor._handlers[LearningActionType.OPEN_LESSON]
    proposal = _proposal(LearningActionType.OPEN_LESSON, {"lesson_id": str(uuid4())})
    with pytest.raises(ForbiddenLearningActionError):
        await executor.execute(learner_id=proposal.learner_id, proposal=proposal)


async def test_start_adaptive_session_delegates_to_adaptive_learning_service() -> None:
    adaptive = FakeAdaptiveLearningService()
    executor = _build_executor(adaptive=adaptive)
    learner_id = uuid4()
    proposal = _proposal(
        LearningActionType.START_ADAPTIVE_SESSION,
        {"session_type": LearningSessionType.DAILY_PRACTICE.value, "goal_minutes": None},
        learner_id=learner_id,
    )
    result = await executor.execute(learner_id=learner_id, proposal=proposal)
    assert result["navigation_target"] == "/practice"
    assert adaptive.start_session_calls == [(learner_id, LearningSessionType.DAILY_PRACTICE, None)]


async def test_start_diagnostic_delegates_to_adaptive_learning_service() -> None:
    adaptive = FakeAdaptiveLearningService()
    executor = _build_executor(adaptive=adaptive)
    learner_id = uuid4()
    proposal = _proposal(
        LearningActionType.START_DIAGNOSTIC_ASSESSMENT, {"skill_ids": [], "maximum_items": 10}, learner_id=learner_id,
    )
    result = await executor.execute(learner_id=learner_id, proposal=proposal)
    assert result["navigation_target"] == "/diagnostic"
    assert result["item_count"] == 3


async def test_open_lesson_returns_navigation_target_when_lesson_exists() -> None:
    lesson = SimpleNamespace(lesson_id=uuid4())
    uow = FakeUow(lesson=lesson)
    executor = _build_executor(uow=uow)
    proposal = _proposal(LearningActionType.OPEN_LESSON, {"lesson_id": str(lesson.lesson_id)})
    result = await executor.execute(learner_id=proposal.learner_id, proposal=proposal)
    assert result["navigation_target"] == f"/lessons/{lesson.lesson_id}"


async def test_open_lesson_raises_when_lesson_missing() -> None:
    uow = FakeUow(lesson=None)
    executor = _build_executor(uow=uow)
    proposal = _proposal(LearningActionType.OPEN_LESSON, {"lesson_id": str(uuid4())})
    with pytest.raises(LearningActionNotFoundError):
        await executor.execute(learner_id=proposal.learner_id, proposal=proposal)


async def test_open_portfolio_rejects_portfolio_owned_by_a_different_learner() -> None:
    other_learner_id = uuid4()
    portfolio = SimpleNamespace(portfolio_id=uuid4(), learner_id=other_learner_id)
    uow = FakeUow(portfolio=portfolio)
    executor = _build_executor(uow=uow)
    requesting_learner_id = uuid4()
    proposal = _proposal(
        LearningActionType.OPEN_PORTFOLIO, {"portfolio_id": str(portfolio.portfolio_id)}, learner_id=requesting_learner_id,
    )
    with pytest.raises(LearningActionNotFoundError):
        await executor.execute(learner_id=requesting_learner_id, proposal=proposal)


async def test_create_tutor_conversation_dispatches_by_context_type() -> None:
    lesson_tutor = FakeTutorConversationService("lesson")
    executor = _build_executor(lesson_tutor=lesson_tutor)
    learner_id = uuid4()
    lesson_id = uuid4()
    proposal = _proposal(
        LearningActionType.CREATE_TUTOR_CONVERSATION,
        {"context_type": TutorContextType.LESSON_HELP.value, "lesson_id": str(lesson_id)},
        learner_id=learner_id,
    )
    result = await executor.execute(learner_id=learner_id, proposal=proposal)
    assert result["navigation_target"] == f"/lessons/{lesson_id}"
    assert lesson_tutor.calls[0][0] == "create_lesson_conversation"


def test_executor_has_no_handler_for_any_trading_or_operational_action_type() -> None:
    """Structural guard: the allow-list dict must never grow a handler
    for anything outside the six approved `LearningActionType` members."""
    executor = _build_executor()
    assert set(executor._handlers.keys()) == set(LearningActionType)

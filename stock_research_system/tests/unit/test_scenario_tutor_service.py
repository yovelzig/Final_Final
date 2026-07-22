"""Unit tests for `ScenarioTutorService`'s conversation-creation validation.

`GroundedAITutorService` and `HistoricalMarketScenarioService` are faked
(their own behavior is covered elsewhere) so these tests focus on
`ScenarioTutorService`'s own responsibilities: existence validation and
pinning `knowledge_cutoff_at` to `scenario.decision_at` before reveal,
and requiring a REVEALED submission after reveal.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from stock_research_core.application.ai_tutor.models import TutorContext
from stock_research_core.application.ai_tutor.scenario_tutor import ScenarioTutorService
from stock_research_core.application.exceptions import (
    InvalidScenarioStateError,
    MarketScenarioNotFoundError,
    ScenarioSubmissionNotFoundError,
)
from stock_research_core.domain.ai_tutor.enums import TutorContextType
from stock_research_core.domain.ai_tutor.models import TutorConversation
from stock_research_core.domain.market_scenarios.enums import (
    MarketScenarioStatus,
    MarketScenarioType,
    ScenarioRevealStatus,
)
from stock_research_core.domain.market_scenarios.models import HistoricalMarketScenario, ScenarioSubmission

DECISION_AT = datetime(2024, 6, 1, tzinfo=timezone.utc)


def _scenario(**overrides) -> HistoricalMarketScenario:
    defaults = dict(
        exercise_id=uuid4(), code="AA_2024_06_01", title="Scenario", description="Description",
        scenario_type=MarketScenarioType.MARKET_REPLAY, status=MarketScenarioStatus.PUBLISHED,
        observation_start_at=DECISION_AT.replace(year=2024, month=1),
        decision_at=DECISION_AT, reveal_end_at=DECISION_AT.replace(month=12),
        interval="1d", source_name="test", focal_security_id=uuid4(), primary_skill_ids=[uuid4()],
        prompt="Prompt", learner_instructions="Instructions", learning_objectives=["Objective"],
        minimum_observation_bars=5, minimum_reveal_bars=1, scenario_version="v1",
    )
    defaults.update(overrides)
    return HistoricalMarketScenario(**defaults)


def _submission(scenario_id, **overrides) -> ScenarioSubmission:
    defaults = dict(
        scenario_id=scenario_id, learner_id=uuid4(), exercise_attempt_id=uuid4(), rubric_version="v1",
    )
    defaults.update(overrides)
    return ScenarioSubmission(**defaults)


class FakeMarketScenarioRepository:
    def __init__(self, scenarios) -> None:
        self._scenarios = {scenario.scenario_id: scenario for scenario in scenarios}

    async def get(self, scenario_id):
        return self._scenarios.get(scenario_id)


class FakeScenarioSubmissionRepository:
    def __init__(self, submissions) -> None:
        self._submissions = {submission.submission_id: submission for submission in submissions}

    async def get(self, submission_id):
        return self._submissions.get(submission_id)

    async def list_for_learner(self, learner_id):
        return [s for s in self._submissions.values() if s.learner_id == learner_id]


class FakeUnitOfWork:
    def __init__(self, market_scenarios, scenario_submissions) -> None:
        self.market_scenarios = market_scenarios
        self.scenario_submissions = scenario_submissions

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args) -> None:
        return None


class FakeTutorService:
    def __init__(self) -> None:
        self.created_contexts: list[TutorContext] = []

    async def create_conversation(self, *, learner_id, context: TutorContext):
        self.created_contexts.append(context)
        return TutorConversation(
            learner_id=learner_id, context_type=context.context_type, scenario_id=context.scenario_id,
            knowledge_cutoff_at=context.knowledge_cutoff_at,
        )


@pytest.mark.asyncio
class TestCreateBeforeDecisionConversation:
    async def test_pins_cutoff_to_decision_at(self) -> None:
        scenario = _scenario()
        submission = _submission(scenario.scenario_id)
        uow_factory = lambda: FakeUnitOfWork(  # noqa: E731
            FakeMarketScenarioRepository([scenario]), FakeScenarioSubmissionRepository([submission])
        )
        tutor_service = FakeTutorService()
        service = ScenarioTutorService(
            tutor_service=tutor_service, unit_of_work_factory=uow_factory, scenario_service=None
        )

        await service.create_before_decision_conversation(
            learner_id=uuid4(), scenario_id=scenario.scenario_id, submission_id=submission.submission_id
        )

        context = tutor_service.created_contexts[0]
        assert context.context_type == TutorContextType.SCENARIO_BEFORE_DECISION
        assert context.knowledge_cutoff_at == scenario.decision_at

    async def test_unknown_scenario_raises(self) -> None:
        uow_factory = lambda: FakeUnitOfWork(  # noqa: E731
            FakeMarketScenarioRepository([]), FakeScenarioSubmissionRepository([])
        )
        service = ScenarioTutorService(
            tutor_service=FakeTutorService(), unit_of_work_factory=uow_factory, scenario_service=None
        )
        with pytest.raises(MarketScenarioNotFoundError):
            await service.create_before_decision_conversation(
                learner_id=uuid4(), scenario_id=uuid4(), submission_id=uuid4()
            )

    async def test_submission_for_different_scenario_raises(self) -> None:
        scenario = _scenario()
        other_submission = _submission(uuid4())  # different scenario_id
        uow_factory = lambda: FakeUnitOfWork(  # noqa: E731
            FakeMarketScenarioRepository([scenario]), FakeScenarioSubmissionRepository([other_submission])
        )
        service = ScenarioTutorService(
            tutor_service=FakeTutorService(), unit_of_work_factory=uow_factory, scenario_service=None
        )
        with pytest.raises(ScenarioSubmissionNotFoundError):
            await service.create_before_decision_conversation(
                learner_id=uuid4(), scenario_id=scenario.scenario_id, submission_id=other_submission.submission_id
            )


@pytest.mark.asyncio
class TestCreateAfterRevealConversation:
    async def test_requires_revealed_submission(self) -> None:
        scenario = _scenario()
        submission = _submission(scenario.scenario_id, reveal_status=ScenarioRevealStatus.HIDDEN)
        uow_factory = lambda: FakeUnitOfWork(  # noqa: E731
            FakeMarketScenarioRepository([scenario]), FakeScenarioSubmissionRepository([submission])
        )
        service = ScenarioTutorService(
            tutor_service=FakeTutorService(), unit_of_work_factory=uow_factory, scenario_service=None
        )
        with pytest.raises(InvalidScenarioStateError):
            await service.create_after_reveal_conversation(learner_id=uuid4(), submission_id=submission.submission_id)

    async def test_unknown_submission_raises(self) -> None:
        uow_factory = lambda: FakeUnitOfWork(  # noqa: E731
            FakeMarketScenarioRepository([]), FakeScenarioSubmissionRepository([])
        )
        service = ScenarioTutorService(
            tutor_service=FakeTutorService(), unit_of_work_factory=uow_factory, scenario_service=None
        )
        with pytest.raises(ScenarioSubmissionNotFoundError):
            await service.create_after_reveal_conversation(learner_id=uuid4(), submission_id=uuid4())

    async def test_revealed_submission_creates_conversation(self) -> None:
        scenario = _scenario()
        submission = _submission(scenario.scenario_id, reveal_status=ScenarioRevealStatus.REVEALED)
        uow_factory = lambda: FakeUnitOfWork(  # noqa: E731
            FakeMarketScenarioRepository([scenario]), FakeScenarioSubmissionRepository([submission])
        )
        tutor_service = FakeTutorService()
        service = ScenarioTutorService(
            tutor_service=tutor_service, unit_of_work_factory=uow_factory, scenario_service=None
        )

        await service.create_after_reveal_conversation(learner_id=uuid4(), submission_id=submission.submission_id)

        context = tutor_service.created_contexts[0]
        assert context.context_type == TutorContextType.SCENARIO_AFTER_REVEAL
        assert context.knowledge_cutoff_at is None

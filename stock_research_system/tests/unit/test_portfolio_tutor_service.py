"""Unit tests for `PortfolioTutorService`.

`VirtualPortfolioService`/`PortfolioValuationService` are faked (their
own analytics are covered elsewhere - this service must never duplicate
them) so these tests focus on `PortfolioTutorService`'s own
responsibilities: portfolio-ownership validation and translating
already-computed metrics into sanitized `structured_context`, never a
trade recommendation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from stock_research_core.application.ai_tutor.models import TutorContext
from stock_research_core.application.ai_tutor.portfolio_tutor import PortfolioTutorService
from stock_research_core.application.exceptions import (
    TutorConversationNotFoundError,
    VirtualPortfolioNotFoundError,
)
from stock_research_core.application.virtual_portfolio.models import PortfolioOverview
from stock_research_core.domain.ai_tutor.enums import TutorContextType
from stock_research_core.domain.ai_tutor.models import TutorConversation
from stock_research_core.domain.virtual_portfolio.models import VirtualPortfolio

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _portfolio(learner_id, **overrides) -> VirtualPortfolio:
    defaults = dict(
        learner_id=learner_id, name="Portfolio", initial_cash=10_000.0, cash_balance=5_000.0,
        simulation_start_at=NOW, current_simulation_at=NOW, portfolio_version="v1",
    )
    defaults.update(overrides)
    return VirtualPortfolio(**defaults)


class FakePortfolioService:
    def __init__(self, overview: PortfolioOverview) -> None:
        self.overview = overview

    async def get_overview(self, portfolio_id):
        return self.overview


class FakeValuationService:
    async def value_portfolio(self, *, portfolio_id, as_of):
        raise AssertionError("value_portfolio should not be called when as_of is None")


class FakeConversationRepository:
    def __init__(self, conversations) -> None:
        self._conversations = conversations

    async def get_conversation(self, conversation_id):
        return self._conversations.get(conversation_id)


class FakeUnitOfWork:
    def __init__(self, conversations) -> None:
        self.tutor_conversations = FakeConversationRepository(conversations)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args) -> None:
        return None


class FakeTutorService:
    def __init__(self) -> None:
        self.created_contexts: list[TutorContext] = []
        self.asked: list[tuple] = []

    async def create_conversation(self, *, learner_id, context: TutorContext):
        self.created_contexts.append(context)
        return TutorConversation(
            learner_id=learner_id, context_type=context.context_type, portfolio_id=context.portfolio_id,
        )

    async def ask(self, *, conversation_id, question, top_k=8, context=None):
        self.asked.append((conversation_id, question, context))
        return "fake-response"


@pytest.mark.asyncio
class TestCreatePortfolioConversation:
    async def test_creates_conversation_for_owning_learner(self) -> None:
        learner_id = uuid4()
        portfolio = _portfolio(learner_id)
        overview = PortfolioOverview(portfolio=portfolio)
        tutor_service = FakeTutorService()
        service = PortfolioTutorService(
            tutor_service=tutor_service, unit_of_work_factory=lambda: FakeUnitOfWork({}),
            portfolio_service=FakePortfolioService(overview), valuation_service=FakeValuationService(),
        )

        await service.create_portfolio_conversation(learner_id=learner_id, portfolio_id=portfolio.portfolio_id)

        context = tutor_service.created_contexts[0]
        assert context.context_type == TutorContextType.PORTFOLIO_EXPLANATION
        assert context.structured_context["portfolio_context_code"] == "virtual_portfolio_risk_education"

    async def test_rejects_non_owning_learner(self) -> None:
        portfolio_owner = uuid4()
        portfolio = _portfolio(portfolio_owner)
        overview = PortfolioOverview(portfolio=portfolio)
        service = PortfolioTutorService(
            tutor_service=FakeTutorService(), unit_of_work_factory=lambda: FakeUnitOfWork({}),
            portfolio_service=FakePortfolioService(overview), valuation_service=FakeValuationService(),
        )

        with pytest.raises(VirtualPortfolioNotFoundError):
            await service.create_portfolio_conversation(learner_id=uuid4(), portfolio_id=portfolio.portfolio_id)


@pytest.mark.asyncio
class TestAsk:
    async def test_structured_context_never_contains_trade_instruction_keys(self) -> None:
        learner_id = uuid4()
        portfolio = _portfolio(learner_id)
        conversation = TutorConversation(
            learner_id=learner_id, context_type=TutorContextType.PORTFOLIO_EXPLANATION,
            portfolio_id=portfolio.portfolio_id,
        )
        overview = PortfolioOverview(portfolio=portfolio)
        tutor_service = FakeTutorService()
        service = PortfolioTutorService(
            tutor_service=tutor_service,
            unit_of_work_factory=lambda: FakeUnitOfWork({conversation.conversation_id: conversation}),
            portfolio_service=FakePortfolioService(overview), valuation_service=FakeValuationService(),
        )

        await service.ask(conversation_id=conversation.conversation_id, question="What does my HHI mean?")

        _conversation_id, _question, context = tutor_service.asked[0]
        forbidden_keys = {"sell_quantity", "buy_quantity", "recommended_security", "trade_action"}
        assert forbidden_keys.isdisjoint(context.structured_context.keys())

    async def test_unknown_conversation_raises(self) -> None:
        service = PortfolioTutorService(
            tutor_service=FakeTutorService(), unit_of_work_factory=lambda: FakeUnitOfWork({}),
            portfolio_service=None, valuation_service=None,
        )
        with pytest.raises(TutorConversationNotFoundError):
            await service.ask(conversation_id=uuid4(), question="q")

"""`PortfolioTutorService`: tutor conversations that explain a learner's
own virtual-portfolio metrics.

Composes `GroundedAITutorService` and reuses
`VirtualPortfolioService.get_overview` / `PortfolioValuationService
.value_portfolio` - no portfolio analytics (HHI, diversification,
drawdown, volatility, turnover) are recomputed here. The tutor may only
*explain* already-calculated metrics; it never creates or executes a
transaction, and `GroundedTutorPromptBuilder` / `RuleBasedTutorGuardrail`
both independently forbid trade prescriptions in the model's answer
text (spec ss16/ss17).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from stock_research_core.application.ai_tutor.models import TutorContext, TutorResponse
from stock_research_core.application.ai_tutor.service import GroundedAITutorService
from stock_research_core.application.exceptions import (
    TutorConversationNotFoundError,
    VirtualPortfolioNotFoundError,
)
from stock_research_core.application.virtual_portfolio.service import VirtualPortfolioService
from stock_research_core.application.virtual_portfolio.valuation_service import PortfolioValuationService
from stock_research_core.domain.ai_tutor.enums import TutorContextType
from stock_research_core.domain.ai_tutor.models import TutorConversation
from stock_research_core.domain.models import utc_now

Clock = Callable[[], datetime]


class PortfolioTutorService:
    """Creates and drives tutor conversations that explain portfolio metrics."""

    def __init__(
        self,
        *,
        tutor_service: GroundedAITutorService,
        unit_of_work_factory: Callable[[], Any],
        portfolio_service: VirtualPortfolioService,
        valuation_service: PortfolioValuationService,
        clock: Clock = utc_now,
    ) -> None:
        self._tutor_service = tutor_service
        self._unit_of_work_factory = unit_of_work_factory
        self._portfolio_service = portfolio_service
        self._valuation_service = valuation_service
        self._clock = clock

    async def create_portfolio_conversation(
        self, *, learner_id: UUID, portfolio_id: UUID, as_of: datetime | None = None
    ) -> TutorConversation:
        overview = await self._portfolio_service.get_overview(portfolio_id)
        if overview.portfolio.learner_id != learner_id:
            raise VirtualPortfolioNotFoundError(
                f"No virtual portfolio '{portfolio_id}' found for learner '{learner_id}'."
            )

        context = TutorContext(
            context_type=TutorContextType.PORTFOLIO_EXPLANATION,
            learner_id=learner_id,
            portfolio_id=portfolio_id,
            structured_context={"portfolio_context_code": "virtual_portfolio_risk_education"},
        )
        return await self._tutor_service.create_conversation(learner_id=learner_id, context=context)

    async def ask(
        self, *, conversation_id: UUID, question: str, as_of: datetime | None = None, top_k: int = 8
    ) -> TutorResponse:
        async with self._unit_of_work_factory() as uow:
            conversation = await uow.tutor_conversations.get_conversation(conversation_id)
        if conversation is None:
            raise TutorConversationNotFoundError(f"No tutor conversation found with id '{conversation_id}'.")
        assert conversation.portfolio_id is not None

        structured_context = await self._build_structured_context(conversation.portfolio_id, as_of=as_of)

        context = TutorContext(
            context_type=conversation.context_type,
            learner_id=conversation.learner_id,
            portfolio_id=conversation.portfolio_id,
            structured_context=structured_context,
        )
        return await self._tutor_service.ask(
            conversation_id=conversation_id, question=question, top_k=top_k, context=context
        )

    async def _build_structured_context(self, portfolio_id: UUID, *, as_of: datetime | None) -> dict[str, Any]:
        structured_context: dict[str, Any] = {"portfolio_context_code": "virtual_portfolio_risk_education"}

        if as_of is not None:
            result = await self._valuation_service.value_portfolio(portfolio_id=portfolio_id, as_of=as_of)
            snapshot, risk_assessment = result.snapshot, result.risk_assessment
            journal_entries_count = None
            transactions_count = None
        else:
            overview = await self._portfolio_service.get_overview(portfolio_id)
            snapshot = overview.latest_valuation
            risk_assessment = overview.latest_risk_assessment
            journal_entries_count = len(overview.recent_journal_entries)
            transactions_count = len(overview.recent_transactions)

        if snapshot is not None:
            structured_context.update(
                {
                    "cash_weight": snapshot.cash_weight,
                    "largest_position_weight": snapshot.largest_position_weight,
                    "largest_sector_weight": snapshot.largest_sector_weight,
                    "position_count": snapshot.position_count,
                    "portfolio_hhi": snapshot.portfolio_hhi,
                    "sector_hhi": snapshot.sector_hhi,
                    "diversification_score": snapshot.diversification_score,
                    "total_return": snapshot.total_return,
                    "benchmark_return": snapshot.benchmark_return,
                    "excess_return": snapshot.excess_return,
                }
            )
        if risk_assessment is not None:
            structured_context.update(
                {
                    "risk_level": risk_assessment.risk_level.value,
                    "drawdown_risk_score": risk_assessment.drawdown_risk_score,
                    "volatility_risk_score": risk_assessment.volatility_risk_score,
                    "turnover_risk_score": risk_assessment.turnover_risk_score,
                    "existing_educational_feedback": " ".join(risk_assessment.educational_feedback),
                }
            )
        if journal_entries_count is not None:
            structured_context["recent_decision_journal_entries_count"] = journal_entries_count
        if transactions_count is not None:
            structured_context["recent_transactions_count"] = transactions_count

        return structured_context

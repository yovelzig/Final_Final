"""SQLAlchemy repository for `TutorGuardrailDecision` persistence."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from stock_research_core.domain.ai_tutor.models import TutorGuardrailDecision
from stock_research_core.infrastructure.database.mappers.ai_tutor_mappers import (
    tutor_guardrail_decision_orm_to_domain,
)
from stock_research_core.infrastructure.database.orm.tutor_guardrail_decision import (
    TutorGuardrailDecisionORM,
)


class SqlAlchemyGuardrailRepository:
    """Persists and queries guardrail decisions."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save_decision(self, decision: TutorGuardrailDecision) -> TutorGuardrailDecision:
        row = TutorGuardrailDecisionORM(
            decision_id=decision.decision_id,
            conversation_id=decision.conversation_id,
            message_id=decision.message_id,
            request_category=decision.request_category.value,
            action=decision.action.value,
            matched_rule_codes=list(decision.matched_rule_codes),
            safe_response_override=decision.safe_response_override,
            policy_version=decision.policy_version,
        )
        self._session.add(row)
        await self._session.flush()
        return tutor_guardrail_decision_orm_to_domain(row)

    async def get_decision(self, decision_id: UUID) -> TutorGuardrailDecision | None:
        row = await self._session.get(TutorGuardrailDecisionORM, decision_id)
        return tutor_guardrail_decision_orm_to_domain(row) if row is not None else None

    async def list_decisions_for_conversation(self, conversation_id: UUID) -> list[TutorGuardrailDecision]:
        statement = (
            select(TutorGuardrailDecisionORM)
            .where(TutorGuardrailDecisionORM.conversation_id == conversation_id)
            .order_by(TutorGuardrailDecisionORM.created_at.asc())
        )
        result = await self._session.execute(statement)
        return [tutor_guardrail_decision_orm_to_domain(row) for row in result.scalars().all()]

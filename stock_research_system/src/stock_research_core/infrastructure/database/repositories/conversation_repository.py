"""SQLAlchemy repository for `TutorConversation` and `TutorMessage` persistence."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from stock_research_core.application.exceptions import PersistenceError
from stock_research_core.domain.ai_tutor.enums import TutorConversationStatus
from stock_research_core.domain.ai_tutor.models import TutorConversation, TutorMessage
from stock_research_core.infrastructure.database.mappers.ai_tutor_mappers import (
    tutor_conversation_orm_to_domain,
    tutor_message_orm_to_domain,
)
from stock_research_core.infrastructure.database.orm.tutor_conversation import TutorConversationORM
from stock_research_core.infrastructure.database.orm.tutor_message import TutorMessageORM


class SqlAlchemyConversationRepository:
    """Persists and queries tutor conversations and their immutable messages."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_conversation(self, conversation: TutorConversation) -> TutorConversation:
        row = TutorConversationORM(
            conversation_id=conversation.conversation_id,
            learner_id=conversation.learner_id,
            status=conversation.status.value,
            context_type=conversation.context_type.value,
            lesson_id=conversation.lesson_id,
            exercise_id=conversation.exercise_id,
            scenario_id=conversation.scenario_id,
            portfolio_id=conversation.portfolio_id,
            knowledge_cutoff_at=conversation.knowledge_cutoff_at,
            closed_at=conversation.closed_at,
        )
        self._session.add(row)
        await self._session.flush()
        return tutor_conversation_orm_to_domain(row)

    async def get_conversation(self, conversation_id: UUID) -> TutorConversation | None:
        row = await self._session.get(TutorConversationORM, conversation_id)
        return tutor_conversation_orm_to_domain(row) if row is not None else None

    async def list_active_conversations_for_learner(self, learner_id: UUID) -> list[TutorConversation]:
        statement = (
            select(TutorConversationORM)
            .where(
                TutorConversationORM.learner_id == learner_id,
                TutorConversationORM.status == TutorConversationStatus.ACTIVE.value,
            )
            .order_by(desc(TutorConversationORM.created_at))
        )
        result = await self._session.execute(statement)
        return [tutor_conversation_orm_to_domain(row) for row in result.scalars().all()]

    async def add_message(self, message: TutorMessage) -> TutorMessage:
        row = TutorMessageORM(
            message_id=message.message_id,
            conversation_id=message.conversation_id,
            role=message.role.value,
            content=message.content,
        )
        self._session.add(row)
        await self._session.flush()
        return tutor_message_orm_to_domain(row)

    async def list_recent_messages(self, conversation_id: UUID, limit: int = 10) -> list[TutorMessage]:
        statement = (
            select(TutorMessageORM)
            .where(TutorMessageORM.conversation_id == conversation_id)
            .order_by(desc(TutorMessageORM.created_at))
            .limit(limit)
        )
        result = await self._session.execute(statement)
        rows = list(result.scalars().all())
        rows.reverse()
        return [tutor_message_orm_to_domain(row) for row in rows]

    async def close_conversation(self, conversation_id: UUID, *, closed_at: datetime) -> TutorConversation:
        row = await self._session.get(TutorConversationORM, conversation_id)
        if row is None:
            raise PersistenceError(f"No tutor conversation found with id '{conversation_id}'.")
        row.status = TutorConversationStatus.CLOSED.value
        row.closed_at = closed_at
        await self._session.flush()
        await self._session.refresh(row)
        return tutor_conversation_orm_to_domain(row)

"""SQLAlchemy repository for `TutorAnswer` and `TutorCitation` persistence."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from stock_research_core.application.exceptions import PersistenceError
from stock_research_core.domain.ai_tutor.enums import GroundingStatus, TutorAnswerStatus
from stock_research_core.domain.ai_tutor.models import TutorAnswer, TutorCitation
from stock_research_core.infrastructure.database.mappers.ai_tutor_mappers import (
    tutor_answer_orm_to_domain,
    tutor_citation_orm_to_domain,
)
from stock_research_core.infrastructure.database.orm.tutor_answer import TutorAnswerORM
from stock_research_core.infrastructure.database.orm.tutor_answer_citation import TutorAnswerCitationORM


class SqlAlchemyTutorAnswerRepository:
    """Persists and queries tutor answers and their citations."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save_answer(self, answer: TutorAnswer) -> TutorAnswer:
        row = TutorAnswerORM(
            answer_id=answer.answer_id,
            conversation_id=answer.conversation_id,
            request_message_id=answer.request_message_id,
            status=answer.status.value,
            provider_type=answer.provider_type.value,
            answer_markdown=answer.answer_markdown,
            request_category=answer.request_category.value,
            grounding_status=answer.grounding_status.value,
            retrieval_run_id=answer.retrieval_run_id,
            guardrail_decision_id=answer.guardrail_decision_id,
            tutor_policy_version=answer.tutor_policy_version,
            prompt_version=answer.prompt_version,
            model_name=answer.model_name,
            model_response_id=answer.model_response_id,
            validated_at=answer.validated_at,
        )
        self._session.add(row)
        await self._session.flush()
        return tutor_answer_orm_to_domain(row)

    async def save_citations(self, citations: list[TutorCitation]) -> list[TutorCitation]:
        rows = [
            TutorAnswerCitationORM(
                citation_id=citation.citation_id,
                answer_id=citation.answer_id,
                chunk_id=citation.chunk_id,
                citation_number=citation.citation_number,
                quoted_excerpt=citation.quoted_excerpt,
                source_title=citation.source_title,
                document_title=citation.document_title,
                heading_path=list(citation.heading_path),
            )
            for citation in citations
        ]
        for row in rows:
            self._session.add(row)
        await self._session.flush()
        return [tutor_citation_orm_to_domain(row) for row in rows]

    async def get_answer(self, answer_id: UUID) -> TutorAnswer | None:
        row = await self._session.get(TutorAnswerORM, answer_id)
        return tutor_answer_orm_to_domain(row) if row is not None else None

    async def list_citations_for_answer(self, answer_id: UUID) -> list[TutorCitation]:
        statement = (
            select(TutorAnswerCitationORM)
            .where(TutorAnswerCitationORM.answer_id == answer_id)
            .order_by(TutorAnswerCitationORM.citation_number.asc())
        )
        result = await self._session.execute(statement)
        return [tutor_citation_orm_to_domain(row) for row in result.scalars().all()]

    async def list_answers_for_conversation(self, conversation_id: UUID) -> list[TutorAnswer]:
        statement = (
            select(TutorAnswerORM)
            .where(TutorAnswerORM.conversation_id == conversation_id)
            .order_by(TutorAnswerORM.created_at.asc())
        )
        result = await self._session.execute(statement)
        return [tutor_answer_orm_to_domain(row) for row in result.scalars().all()]

    async def update_validation_status(
        self,
        answer_id: UUID,
        *,
        status: TutorAnswerStatus,
        grounding_status: GroundingStatus,
        validated_at: datetime | None,
    ) -> TutorAnswer:
        row = await self._session.get(TutorAnswerORM, answer_id)
        if row is None:
            raise PersistenceError(f"No tutor answer found with id '{answer_id}'.")
        row.status = status.value
        row.grounding_status = grounding_status.value
        row.validated_at = validated_at
        await self._session.flush()
        await self._session.refresh(row)
        return tutor_answer_orm_to_domain(row)

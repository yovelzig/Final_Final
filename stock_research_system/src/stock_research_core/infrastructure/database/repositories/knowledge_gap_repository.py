"""SQLAlchemy repository for `TutorKnowledgeGap` persistence.

`target_skill_ids` lives in the `tutor_knowledge_gap_skills` association
table and is replaced wholesale on each upsert, matching the pattern
used throughout this codebase for skill associations.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from stock_research_core.application.exceptions import PersistenceError
from stock_research_core.domain.ai_tutor.models import TutorKnowledgeGap
from stock_research_core.infrastructure.database.mappers.ai_tutor_mappers import (
    tutor_knowledge_gap_orm_to_domain,
)
from stock_research_core.infrastructure.database.orm.tutor_knowledge_gap import (
    TutorKnowledgeGapORM,
    TutorKnowledgeGapSkillORM,
)


class SqlAlchemyKnowledgeGapRepository:
    """Persists and queries tracked knowledge gaps."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_gap(self, gap: TutorKnowledgeGap) -> TutorKnowledgeGap:
        insert_stmt = pg_insert(TutorKnowledgeGapORM).values(
            gap_id=gap.gap_id,
            learner_id=gap.learner_id,
            conversation_id=gap.conversation_id,
            message_id=gap.message_id,
            normalized_question=gap.normalized_question,
            context_type=gap.context_type.value,
            occurrence_count=gap.occurrence_count,
            first_seen_at=gap.first_seen_at,
            last_seen_at=gap.last_seen_at,
            resolved=gap.resolved,
            resolved_at=gap.resolved_at,
            resolution_document_id=gap.resolution_document_id,
        )
        statement = insert_stmt.on_conflict_do_update(
            index_elements=["gap_id"],
            set_={
                "occurrence_count": insert_stmt.excluded.occurrence_count,
                "last_seen_at": insert_stmt.excluded.last_seen_at,
                "resolved": insert_stmt.excluded.resolved,
                "resolved_at": insert_stmt.excluded.resolved_at,
                "resolution_document_id": insert_stmt.excluded.resolution_document_id,
                "updated_at": func.now(),
            },
        )
        await self._session.execute(statement)

        await self._session.execute(
            delete(TutorKnowledgeGapSkillORM).where(TutorKnowledgeGapSkillORM.gap_id == gap.gap_id)
        )
        for skill_id in gap.target_skill_ids:
            self._session.add(TutorKnowledgeGapSkillORM(gap_id=gap.gap_id, skill_id=skill_id))
        await self._session.flush()

        row = await self._session.get(TutorKnowledgeGapORM, gap.gap_id)
        assert row is not None
        return tutor_knowledge_gap_orm_to_domain(row, list(gap.target_skill_ids))

    async def get_by_question_and_context(
        self, normalized_question: str, context_type: str
    ) -> TutorKnowledgeGap | None:
        statement = select(TutorKnowledgeGapORM).where(
            TutorKnowledgeGapORM.normalized_question == normalized_question,
            TutorKnowledgeGapORM.context_type == context_type,
            TutorKnowledgeGapORM.resolved.is_(False),
        )
        result = await self._session.execute(statement)
        row = result.scalars().first()
        if row is None:
            return None
        skill_ids = await self._load_skill_ids(row.gap_id)
        return tutor_knowledge_gap_orm_to_domain(row, skill_ids)

    async def list_unresolved_gaps(self, limit: int = 50) -> list[TutorKnowledgeGap]:
        statement = (
            select(TutorKnowledgeGapORM)
            .where(TutorKnowledgeGapORM.resolved.is_(False))
            .order_by(TutorKnowledgeGapORM.occurrence_count.desc(), TutorKnowledgeGapORM.last_seen_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(statement)
        rows = result.scalars().all()
        gaps = []
        for row in rows:
            skill_ids = await self._load_skill_ids(row.gap_id)
            gaps.append(tutor_knowledge_gap_orm_to_domain(row, skill_ids))
        return gaps

    async def resolve_gap(
        self, gap_id: UUID, *, resolved_at: datetime, resolution_document_id: UUID | None
    ) -> TutorKnowledgeGap:
        row = await self._session.get(TutorKnowledgeGapORM, gap_id)
        if row is None:
            raise PersistenceError(f"No tutor knowledge gap found with id '{gap_id}'.")
        row.resolved = True
        row.resolved_at = resolved_at
        row.resolution_document_id = resolution_document_id
        await self._session.flush()
        await self._session.refresh(row)
        skill_ids = await self._load_skill_ids(gap_id)
        return tutor_knowledge_gap_orm_to_domain(row, skill_ids)

    async def count_repeated_gaps(self, minimum_occurrences: int = 2) -> int:
        statement = select(func.count()).where(
            TutorKnowledgeGapORM.occurrence_count >= minimum_occurrences,
            TutorKnowledgeGapORM.resolved.is_(False),
        )
        result = await self._session.execute(statement)
        return int(result.scalar_one())

    async def _load_skill_ids(self, gap_id: UUID) -> list[UUID]:
        statement = select(TutorKnowledgeGapSkillORM.skill_id).where(
            TutorKnowledgeGapSkillORM.gap_id == gap_id
        )
        result = await self._session.execute(statement)
        return list(result.scalars().all())

"""SQLAlchemy repository for `DiagnosticAssessment` / `DiagnosticAssessmentItem` persistence."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from stock_research_core.application.exceptions import PersistenceError
from stock_research_core.domain.adaptive_learning.models import (
    DiagnosticAssessment,
    DiagnosticAssessmentItem,
)
from stock_research_core.infrastructure.database.mappers.adaptive_learning_mappers import (
    diagnostic_assessment_item_orm_to_domain,
    diagnostic_assessment_orm_to_domain,
)
from stock_research_core.infrastructure.database.orm.diagnostic_assessment import (
    DiagnosticAssessmentORM,
    DiagnosticAssessmentSkillORM,
)
from stock_research_core.infrastructure.database.orm.diagnostic_assessment_item import (
    DiagnosticAssessmentItemORM,
    DiagnosticItemSkillORM,
)


class SqlAlchemyDiagnosticRepository:
    """Persists and queries `DiagnosticAssessment` and `DiagnosticAssessmentItem` rows."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_assessment(self, assessment: DiagnosticAssessment) -> DiagnosticAssessment:
        row = DiagnosticAssessmentORM(
            assessment_id=assessment.assessment_id,
            learner_id=assessment.learner_id,
            status=assessment.status.value,
            maximum_items=assessment.maximum_items,
            started_at=assessment.started_at,
            completed_at=assessment.completed_at,
            policy_version=assessment.policy_version,
        )
        self._session.add(row)
        for skill_id in assessment.skill_ids:
            self._session.add(
                DiagnosticAssessmentSkillORM(assessment_id=assessment.assessment_id, skill_id=skill_id)
            )
        await self._session.flush()
        return diagnostic_assessment_orm_to_domain(row, list(assessment.skill_ids))

    async def get_assessment(self, assessment_id: UUID) -> DiagnosticAssessment | None:
        row = await self._session.get(DiagnosticAssessmentORM, assessment_id)
        if row is None:
            return None
        skill_ids = await self._load_assessment_skills(assessment_id)
        return diagnostic_assessment_orm_to_domain(row, skill_ids)

    async def update_assessment(self, assessment: DiagnosticAssessment) -> DiagnosticAssessment:
        row = await self._session.get(DiagnosticAssessmentORM, assessment.assessment_id)
        if row is None:
            raise PersistenceError(
                f"No diagnostic assessment found with id '{assessment.assessment_id}'."
            )
        row.status = assessment.status.value
        row.started_at = assessment.started_at
        row.completed_at = assessment.completed_at
        await self._session.flush()
        await self._session.refresh(row)
        skill_ids = await self._load_assessment_skills(assessment.assessment_id)
        return diagnostic_assessment_orm_to_domain(row, skill_ids)

    async def _load_assessment_skills(self, assessment_id: UUID) -> list[UUID]:
        result = await self._session.execute(
            select(DiagnosticAssessmentSkillORM.skill_id).where(
                DiagnosticAssessmentSkillORM.assessment_id == assessment_id
            )
        )
        return list(result.scalars().all())

    async def save_items(self, items: list[DiagnosticAssessmentItem]) -> int:
        if not items:
            return 0
        for item in items:
            row = DiagnosticAssessmentItemORM(
                item_id=item.item_id,
                assessment_id=item.assessment_id,
                exercise_id=item.exercise_id,
                position=item.position,
                attempt_id=item.attempt_id,
                selected_at=item.selected_at,
                completed_at=item.completed_at,
                normalized_score=item.normalized_score,
            )
            self._session.add(row)
            for skill_id in item.skill_ids:
                self._session.add(DiagnosticItemSkillORM(item_id=item.item_id, skill_id=skill_id))
        await self._session.flush()
        return len(items)

    async def get_item(self, item_id: UUID) -> DiagnosticAssessmentItem | None:
        row = await self._session.get(DiagnosticAssessmentItemORM, item_id)
        if row is None:
            return None
        skill_ids = await self._load_item_skills(item_id)
        return diagnostic_assessment_item_orm_to_domain(row, skill_ids)

    async def update_item(self, item: DiagnosticAssessmentItem) -> DiagnosticAssessmentItem:
        row = await self._session.get(DiagnosticAssessmentItemORM, item.item_id)
        if row is None:
            raise PersistenceError(f"No diagnostic item found with id '{item.item_id}'.")
        row.attempt_id = item.attempt_id
        row.completed_at = item.completed_at
        row.normalized_score = item.normalized_score
        await self._session.flush()
        skill_ids = await self._load_item_skills(item.item_id)
        return diagnostic_assessment_item_orm_to_domain(row, skill_ids)

    async def _load_item_skills(self, item_id: UUID) -> list[UUID]:
        result = await self._session.execute(
            select(DiagnosticItemSkillORM.skill_id).where(DiagnosticItemSkillORM.item_id == item_id)
        )
        return list(result.scalars().all())

    async def list_items(self, assessment_id: UUID) -> list[DiagnosticAssessmentItem]:
        statement = (
            select(DiagnosticAssessmentItemORM)
            .where(DiagnosticAssessmentItemORM.assessment_id == assessment_id)
            .order_by(DiagnosticAssessmentItemORM.position.asc())
        )
        result = await self._session.execute(statement)
        rows = result.scalars().all()
        items = []
        for row in rows:
            skill_ids = await self._load_item_skills(row.item_id)
            items.append(diagnostic_assessment_item_orm_to_domain(row, skill_ids))
        return items

    async def list_recent_assessments(
        self, learner_id: UUID, limit: int = 10
    ) -> list[DiagnosticAssessment]:
        statement = (
            select(DiagnosticAssessmentORM)
            .where(DiagnosticAssessmentORM.learner_id == learner_id)
            .order_by(DiagnosticAssessmentORM.created_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(statement)
        rows = result.scalars().all()
        assessments = []
        for row in rows:
            skill_ids = await self._load_assessment_skills(row.assessment_id)
            assessments.append(diagnostic_assessment_orm_to_domain(row, skill_ids))
        return assessments

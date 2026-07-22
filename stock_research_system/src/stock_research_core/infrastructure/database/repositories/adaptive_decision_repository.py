"""SQLAlchemy repository for `AdaptiveDecision` audit-record persistence."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from stock_research_core.application.exceptions import PersistenceError
from stock_research_core.domain.adaptive_learning.models import AdaptiveDecision
from stock_research_core.infrastructure.database.mappers.adaptive_learning_mappers import (
    adaptive_decision_orm_to_domain,
)
from stock_research_core.infrastructure.database.orm.adaptive_decision import (
    AdaptiveDecisionORM,
    AdaptiveDecisionReasonORM,
    AdaptiveDecisionTargetSkillORM,
)


class SqlAlchemyAdaptiveDecisionRepository:
    """Persists and queries `AdaptiveDecision` audit records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_decision(self, decision: AdaptiveDecision) -> AdaptiveDecision:
        row = AdaptiveDecisionORM(
            decision_id=decision.decision_id,
            learner_id=decision.learner_id,
            session_id=decision.session_id,
            recommendation_type=decision.recommendation_type.value,
            status=decision.status.value,
            recommended_exercise_id=decision.recommended_exercise_id,
            recommended_lesson_id=decision.recommended_lesson_id,
            priority_score=decision.priority_score,
            recommended_difficulty_score=decision.recommended_difficulty_score,
            policy_version=decision.policy_version,
            explanation=decision.explanation,
            input_snapshot=decision.input_snapshot,
            generated_at=decision.generated_at,
            accepted_at=decision.accepted_at,
            completed_at=decision.completed_at,
            skipped_at=decision.skipped_at,
            expires_at=decision.expires_at,
        )
        self._session.add(row)
        for skill_id in decision.target_skill_ids:
            self._session.add(
                AdaptiveDecisionTargetSkillORM(decision_id=decision.decision_id, skill_id=skill_id)
            )
        for reason in decision.reason_codes:
            self._session.add(
                AdaptiveDecisionReasonORM(decision_id=decision.decision_id, reason_code=reason.value)
            )
        await self._session.flush()
        return adaptive_decision_orm_to_domain(
            row,
            list(decision.target_skill_ids),
            [reason.value for reason in decision.reason_codes],
        )

    async def get_decision(self, decision_id: UUID) -> AdaptiveDecision | None:
        row = await self._session.get(AdaptiveDecisionORM, decision_id)
        if row is None:
            return None
        target_skill_ids, reason_codes = await self._load_associations(decision_id)
        return adaptive_decision_orm_to_domain(row, target_skill_ids, reason_codes)

    async def update_decision(self, decision: AdaptiveDecision) -> AdaptiveDecision:
        row = await self._session.get(AdaptiveDecisionORM, decision.decision_id)
        if row is None:
            raise PersistenceError(f"No adaptive decision found with id '{decision.decision_id}'.")
        row.status = decision.status.value
        row.accepted_at = decision.accepted_at
        row.completed_at = decision.completed_at
        row.skipped_at = decision.skipped_at
        row.expires_at = decision.expires_at
        await self._session.flush()
        target_skill_ids, reason_codes = await self._load_associations(decision.decision_id)
        return adaptive_decision_orm_to_domain(row, target_skill_ids, reason_codes)

    async def _load_associations(self, decision_id: UUID) -> tuple[list[UUID], list[str]]:
        target_result = await self._session.execute(
            select(AdaptiveDecisionTargetSkillORM.skill_id).where(
                AdaptiveDecisionTargetSkillORM.decision_id == decision_id
            )
        )
        reason_result = await self._session.execute(
            select(AdaptiveDecisionReasonORM.reason_code).where(
                AdaptiveDecisionReasonORM.decision_id == decision_id
            )
        )
        return list(target_result.scalars().all()), list(reason_result.scalars().all())

    async def list_recent_decisions(self, learner_id: UUID, limit: int = 10) -> list[AdaptiveDecision]:
        statement = (
            select(AdaptiveDecisionORM)
            .where(AdaptiveDecisionORM.learner_id == learner_id)
            .order_by(AdaptiveDecisionORM.generated_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(statement)
        rows = result.scalars().all()
        decisions = []
        for row in rows:
            target_skill_ids, reason_codes = await self._load_associations(row.decision_id)
            decisions.append(adaptive_decision_orm_to_domain(row, target_skill_ids, reason_codes))
        return decisions

    async def list_session_decisions(self, session_id: UUID) -> list[AdaptiveDecision]:
        statement = (
            select(AdaptiveDecisionORM)
            .where(AdaptiveDecisionORM.session_id == session_id)
            .order_by(AdaptiveDecisionORM.generated_at.asc())
        )
        result = await self._session.execute(statement)
        rows = result.scalars().all()
        decisions = []
        for row in rows:
            target_skill_ids, reason_codes = await self._load_associations(row.decision_id)
            decisions.append(adaptive_decision_orm_to_domain(row, target_skill_ids, reason_codes))
        return decisions

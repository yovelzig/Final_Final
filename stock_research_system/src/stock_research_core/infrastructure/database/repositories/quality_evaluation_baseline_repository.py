"""SQLAlchemy repository for `QualityEvaluationBaseline` persistence
(Phase 13). Baseline approval is ADMIN-only and row-locked (spec section
20) so two concurrent approval requests for the same suite can never both
believe they set the approved baseline."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from stock_research_core.application.exceptions import PersistenceError
from stock_research_core.domain.quality_evaluation.models import QualityEvaluationBaseline
from stock_research_core.infrastructure.database.mappers.quality_evaluation_mappers import (
    quality_evaluation_baseline_orm_to_domain,
)
from stock_research_core.infrastructure.database.orm.quality_evaluation_baseline import QualityEvaluationBaselineORM


class SqlAlchemyQualityEvaluationBaselineRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, baseline: QualityEvaluationBaseline) -> QualityEvaluationBaseline:
        row = QualityEvaluationBaselineORM(
            baseline_id=baseline.baseline_id, suite_id=baseline.suite_id, run_id=baseline.run_id,
            name=baseline.name, approved=baseline.approved, approved_by_account_id=baseline.approved_by_account_id,
            metric_summary=dict(baseline.metric_summary), safety_gate_summary=dict(baseline.safety_gate_summary),
            approved_at=baseline.approved_at,
        )
        self._session.add(row)
        await self._session.flush()
        return quality_evaluation_baseline_orm_to_domain(row)

    async def get_by_id(self, baseline_id: UUID) -> QualityEvaluationBaseline | None:
        row = await self._session.get(QualityEvaluationBaselineORM, baseline_id)
        return quality_evaluation_baseline_orm_to_domain(row) if row is not None else None

    async def list_for_suite(self, suite_id: UUID) -> list[QualityEvaluationBaseline]:
        statement = (
            select(QualityEvaluationBaselineORM).where(QualityEvaluationBaselineORM.suite_id == suite_id)
            .order_by(QualityEvaluationBaselineORM.created_at.desc())
        )
        result = await self._session.execute(statement)
        return [quality_evaluation_baseline_orm_to_domain(row) for row in result.scalars().all()]

    async def get_approved_for_suite(self, suite_id: UUID) -> QualityEvaluationBaseline | None:
        statement = (
            select(QualityEvaluationBaselineORM)
            .where(QualityEvaluationBaselineORM.suite_id == suite_id, QualityEvaluationBaselineORM.approved.is_(True))
            .order_by(QualityEvaluationBaselineORM.approved_at.desc())
        )
        result = await self._session.execute(statement)
        row = result.scalars().first()
        return quality_evaluation_baseline_orm_to_domain(row) if row is not None else None

    async def approve(
        self, baseline_id: UUID, *, approved_by_account_id: UUID, approved_at: datetime,
    ) -> QualityEvaluationBaseline:
        statement = (
            select(QualityEvaluationBaselineORM)
            .where(QualityEvaluationBaselineORM.baseline_id == baseline_id)
            .with_for_update()
        )
        result = await self._session.execute(statement)
        row = result.scalars().first()
        if row is None:
            raise PersistenceError(f"Baseline '{baseline_id}' not found.")
        row.approved = True
        row.approved_by_account_id = approved_by_account_id
        row.approved_at = approved_at
        await self._session.flush()
        return quality_evaluation_baseline_orm_to_domain(row)

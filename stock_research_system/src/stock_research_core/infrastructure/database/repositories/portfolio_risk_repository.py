"""SQLAlchemy repository for `PortfolioRiskAssessment` persistence."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from stock_research_core.domain.virtual_portfolio.models import PortfolioRiskAssessment
from stock_research_core.infrastructure.database.mappers.virtual_portfolio_mappers import (
    portfolio_risk_assessment_orm_to_domain,
)
from stock_research_core.infrastructure.database.orm.portfolio_risk_assessment import (
    PortfolioRiskAssessmentORM,
    PortfolioRiskFeedbackCodeORM,
    PortfolioRiskSkillORM,
)

_DEFAULT_HISTORY_LIMIT = 20

_UPDATE_COLUMNS = [
    "risk_level",
    "position_concentration_score",
    "sector_concentration_score",
    "diversification_score",
    "drawdown_risk_score",
    "volatility_risk_score",
    "turnover_risk_score",
    "summary",
    "educational_feedback",
    "calculated_at",
]


class SqlAlchemyPortfolioRiskRepository:
    """Persists and queries `PortfolioRiskAssessment` rows."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, assessment: PortfolioRiskAssessment) -> PortfolioRiskAssessment:
        insert_stmt = pg_insert(PortfolioRiskAssessmentORM).values(
            assessment_id=assessment.assessment_id,
            portfolio_id=assessment.portfolio_id,
            snapshot_id=assessment.snapshot_id,
            risk_level=assessment.risk_level.value,
            position_concentration_score=assessment.position_concentration_score,
            sector_concentration_score=assessment.sector_concentration_score,
            diversification_score=assessment.diversification_score,
            drawdown_risk_score=assessment.drawdown_risk_score,
            volatility_risk_score=assessment.volatility_risk_score,
            turnover_risk_score=assessment.turnover_risk_score,
            summary=assessment.summary,
            educational_feedback=assessment.educational_feedback,
            policy_version=assessment.policy_version,
            calculated_at=assessment.calculated_at,
        )
        statement = insert_stmt.on_conflict_do_update(
            constraint="uq_portfolio_risk_assessments_snapshot_version",
            set_={column: getattr(insert_stmt.excluded, column) for column in _UPDATE_COLUMNS},
        ).returning(PortfolioRiskAssessmentORM.assessment_id)
        result = await self._session.execute(statement)
        canonical_id = result.scalar_one()

        await self._session.execute(
            delete(PortfolioRiskFeedbackCodeORM).where(
                PortfolioRiskFeedbackCodeORM.assessment_id == canonical_id
            )
        )
        await self._session.execute(
            delete(PortfolioRiskSkillORM).where(PortfolioRiskSkillORM.assessment_id == canonical_id)
        )
        for code in assessment.feedback_codes:
            self._session.add(
                PortfolioRiskFeedbackCodeORM(assessment_id=canonical_id, feedback_code=code.value)
            )
        for skill_id in assessment.related_skill_ids:
            self._session.add(PortfolioRiskSkillORM(assessment_id=canonical_id, skill_id=skill_id))
        await self._session.flush()

        row = await self._session.get(PortfolioRiskAssessmentORM, canonical_id)
        assert row is not None
        feedback_codes, skill_ids = await self._load_associations(canonical_id)
        return portfolio_risk_assessment_orm_to_domain(row, feedback_codes, skill_ids)

    async def get_by_snapshot(
        self, snapshot_id: UUID, policy_version: str
    ) -> PortfolioRiskAssessment | None:
        statement = select(PortfolioRiskAssessmentORM).where(
            PortfolioRiskAssessmentORM.snapshot_id == snapshot_id,
            PortfolioRiskAssessmentORM.policy_version == policy_version,
        )
        result = await self._session.execute(statement)
        row = result.scalars().first()
        if row is None:
            return None
        feedback_codes, skill_ids = await self._load_associations(row.assessment_id)
        return portfolio_risk_assessment_orm_to_domain(row, feedback_codes, skill_ids)

    async def get_latest(self, portfolio_id: UUID) -> PortfolioRiskAssessment | None:
        statement = (
            select(PortfolioRiskAssessmentORM)
            .where(PortfolioRiskAssessmentORM.portfolio_id == portfolio_id)
            .order_by(PortfolioRiskAssessmentORM.calculated_at.desc())
            .limit(1)
        )
        result = await self._session.execute(statement)
        row = result.scalars().first()
        if row is None:
            return None
        feedback_codes, skill_ids = await self._load_associations(row.assessment_id)
        return portfolio_risk_assessment_orm_to_domain(row, feedback_codes, skill_ids)

    async def list_history(
        self, portfolio_id: UUID, limit: int = _DEFAULT_HISTORY_LIMIT
    ) -> list[PortfolioRiskAssessment]:
        statement = (
            select(PortfolioRiskAssessmentORM)
            .where(PortfolioRiskAssessmentORM.portfolio_id == portfolio_id)
            .order_by(PortfolioRiskAssessmentORM.calculated_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(statement)
        rows = result.scalars().all()
        assessments = []
        for row in rows:
            feedback_codes, skill_ids = await self._load_associations(row.assessment_id)
            assessments.append(portfolio_risk_assessment_orm_to_domain(row, feedback_codes, skill_ids))
        return assessments

    async def _load_associations(self, assessment_id: UUID) -> tuple[list[str], list[UUID]]:
        codes = (
            await self._session.execute(
                select(PortfolioRiskFeedbackCodeORM.feedback_code).where(
                    PortfolioRiskFeedbackCodeORM.assessment_id == assessment_id
                )
            )
        ).scalars().all()
        skills = (
            await self._session.execute(
                select(PortfolioRiskSkillORM.skill_id).where(
                    PortfolioRiskSkillORM.assessment_id == assessment_id
                )
            )
        ).scalars().all()
        return list(codes), list(skills)

"""SQLAlchemy repository for `PortfolioValuationRun` audit-record persistence."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from stock_research_core.application.exceptions import PersistenceError
from stock_research_core.domain.virtual_portfolio.enums import PortfolioValuationRunStatus
from stock_research_core.domain.virtual_portfolio.models import PortfolioValuationRun
from stock_research_core.infrastructure.database.mappers.virtual_portfolio_mappers import (
    portfolio_valuation_run_orm_to_domain,
)
from stock_research_core.infrastructure.database.orm.portfolio_valuation_run import (
    PortfolioValuationRunORM,
)

_DEFAULT_RECENT_LIMIT = 10


class SqlAlchemyPortfolioValuationRunRepository:
    """Persists and queries `PortfolioValuationRun` audit records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_started(self, run: PortfolioValuationRun) -> PortfolioValuationRun:
        row = PortfolioValuationRunORM(
            run_id=run.run_id,
            portfolio_id=run.portfolio_id,
            status=run.status.value,
            requested_as_of=run.requested_as_of,
            valuation_version=run.valuation_version,
            risk_policy_version=run.risk_policy_version,
            holding_count=run.holding_count,
            priced_holding_count=run.priced_holding_count,
            missing_price_count=run.missing_price_count,
            started_at=run.started_at,
        )
        self._session.add(row)
        await self._session.flush()
        return portfolio_valuation_run_orm_to_domain(row)

    async def mark_completed(
        self, run_id: UUID, *, completed_at: datetime, priced_holding_count: int, missing_price_count: int
    ) -> PortfolioValuationRun:
        row = await self._session.get(PortfolioValuationRunORM, run_id)
        if row is None:
            raise PersistenceError(f"No portfolio valuation run found with id '{run_id}'.")
        row.status = PortfolioValuationRunStatus.COMPLETED.value
        row.completed_at = completed_at
        row.priced_holding_count = priced_holding_count
        row.missing_price_count = missing_price_count
        await self._session.flush()
        return portfolio_valuation_run_orm_to_domain(row)

    async def mark_failed(
        self, run_id: UUID, *, completed_at: datetime, error_type: str, error_message: str
    ) -> PortfolioValuationRun:
        row = await self._session.get(PortfolioValuationRunORM, run_id)
        if row is None:
            raise PersistenceError(f"No portfolio valuation run found with id '{run_id}'.")
        row.status = PortfolioValuationRunStatus.FAILED.value
        row.completed_at = completed_at
        row.error_type = error_type
        row.error_message = error_message
        await self._session.flush()
        return portfolio_valuation_run_orm_to_domain(row)

    async def mark_no_price_data(
        self, run_id: UUID, *, completed_at: datetime, missing_price_count: int
    ) -> PortfolioValuationRun:
        row = await self._session.get(PortfolioValuationRunORM, run_id)
        if row is None:
            raise PersistenceError(f"No portfolio valuation run found with id '{run_id}'.")
        row.status = PortfolioValuationRunStatus.NO_PRICE_DATA.value
        row.completed_at = completed_at
        row.missing_price_count = missing_price_count
        await self._session.flush()
        return portfolio_valuation_run_orm_to_domain(row)

    async def get(self, run_id: UUID) -> PortfolioValuationRun | None:
        row = await self._session.get(PortfolioValuationRunORM, run_id)
        return portfolio_valuation_run_orm_to_domain(row) if row is not None else None

    async def list_recent(
        self, portfolio_id: UUID, limit: int = _DEFAULT_RECENT_LIMIT
    ) -> list[PortfolioValuationRun]:
        statement = (
            select(PortfolioValuationRunORM)
            .where(PortfolioValuationRunORM.portfolio_id == portfolio_id)
            .order_by(PortfolioValuationRunORM.started_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(statement)
        return [portfolio_valuation_run_orm_to_domain(row) for row in result.scalars().all()]

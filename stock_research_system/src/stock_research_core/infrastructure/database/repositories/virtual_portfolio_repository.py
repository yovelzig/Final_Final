"""SQLAlchemy repository for `VirtualPortfolio` persistence."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from stock_research_core.application.exceptions import PersistenceError
from stock_research_core.domain.virtual_portfolio.enums import VirtualPortfolioStatus
from stock_research_core.domain.virtual_portfolio.models import VirtualPortfolio
from stock_research_core.infrastructure.database.mappers.virtual_portfolio_mappers import (
    virtual_portfolio_orm_to_domain,
)
from stock_research_core.infrastructure.database.orm.virtual_portfolio import VirtualPortfolioORM


class SqlAlchemyVirtualPortfolioRepository:
    """Persists and queries `VirtualPortfolio` rows."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, portfolio: VirtualPortfolio) -> VirtualPortfolio:
        row = VirtualPortfolioORM(
            portfolio_id=portfolio.portfolio_id,
            learner_id=portfolio.learner_id,
            name=portfolio.name,
            description=portfolio.description,
            base_currency=portfolio.base_currency,
            initial_cash=portfolio.initial_cash,
            cash_balance=portfolio.cash_balance,
            benchmark_security_id=portfolio.benchmark_security_id,
            status=portfolio.status.value,
            allow_fractional_shares=portfolio.allow_fractional_shares,
            require_decision_journal=portfolio.require_decision_journal,
            fixed_transaction_fee=portfolio.fixed_transaction_fee,
            transaction_fee_bps=portfolio.transaction_fee_bps,
            simulation_start_at=portfolio.simulation_start_at,
            current_simulation_at=portfolio.current_simulation_at,
            portfolio_version=portfolio.portfolio_version,
        )
        self._session.add(row)
        await self._session.flush()
        return virtual_portfolio_orm_to_domain(row)

    async def get(self, portfolio_id: UUID, *, for_update: bool = False) -> VirtualPortfolio | None:
        statement = select(VirtualPortfolioORM).where(VirtualPortfolioORM.portfolio_id == portfolio_id)
        if for_update:
            statement = statement.with_for_update()
        result = await self._session.execute(statement)
        row = result.scalars().first()
        return virtual_portfolio_orm_to_domain(row) if row is not None else None

    async def list_for_learner(
        self, learner_id: UUID, active_only: bool = False
    ) -> list[VirtualPortfolio]:
        statement = select(VirtualPortfolioORM).where(VirtualPortfolioORM.learner_id == learner_id)
        if active_only:
            statement = statement.where(VirtualPortfolioORM.status == VirtualPortfolioStatus.ACTIVE.value)
        statement = statement.order_by(VirtualPortfolioORM.created_at.asc())
        result = await self._session.execute(statement)
        return [virtual_portfolio_orm_to_domain(row) for row in result.scalars().all()]

    async def list_all_active_ids(self, *, limit: int = 10_000) -> list[UUID]:
        statement = (
            select(VirtualPortfolioORM.portfolio_id)
            .where(VirtualPortfolioORM.status == VirtualPortfolioStatus.ACTIVE.value)
            .order_by(VirtualPortfolioORM.created_at.asc())
            .limit(limit)
        )
        result = await self._session.execute(statement)
        return list(result.scalars().all())

    async def update(self, portfolio: VirtualPortfolio) -> VirtualPortfolio:
        row = await self._session.get(VirtualPortfolioORM, portfolio.portfolio_id)
        if row is None:
            raise PersistenceError(f"No virtual portfolio found with id '{portfolio.portfolio_id}'.")
        row.name = portfolio.name
        row.description = portfolio.description
        row.cash_balance = portfolio.cash_balance
        row.status = portfolio.status.value
        row.allow_fractional_shares = portfolio.allow_fractional_shares
        row.require_decision_journal = portfolio.require_decision_journal
        row.fixed_transaction_fee = portfolio.fixed_transaction_fee
        row.transaction_fee_bps = portfolio.transaction_fee_bps
        row.current_simulation_at = portfolio.current_simulation_at
        await self._session.flush()
        await self._session.refresh(row)
        return virtual_portfolio_orm_to_domain(row)

"""SQLAlchemy repository for `PortfolioHolding` persistence."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from stock_research_core.domain.virtual_portfolio.models import PortfolioHolding
from stock_research_core.infrastructure.database.mappers.virtual_portfolio_mappers import (
    portfolio_holding_orm_to_domain,
)
from stock_research_core.infrastructure.database.orm.portfolio_holding import PortfolioHoldingORM


class SqlAlchemyPortfolioHoldingRepository:
    """Persists and queries `PortfolioHolding` rows. Unique per (portfolio, security)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(
        self, portfolio_id: UUID, security_id: UUID, *, for_update: bool = False
    ) -> PortfolioHolding | None:
        statement = select(PortfolioHoldingORM).where(
            PortfolioHoldingORM.portfolio_id == portfolio_id, PortfolioHoldingORM.security_id == security_id
        )
        if for_update:
            statement = statement.with_for_update()
        result = await self._session.execute(statement)
        row = result.scalars().first()
        return portfolio_holding_orm_to_domain(row) if row is not None else None

    async def list_for_portfolio(
        self, portfolio_id: UUID, include_zero: bool = False
    ) -> list[PortfolioHolding]:
        statement = select(PortfolioHoldingORM).where(PortfolioHoldingORM.portfolio_id == portfolio_id)
        if not include_zero:
            statement = statement.where(PortfolioHoldingORM.quantity > 0)
        statement = statement.order_by(PortfolioHoldingORM.security_id.asc())
        result = await self._session.execute(statement)
        return [portfolio_holding_orm_to_domain(row) for row in result.scalars().all()]

    async def upsert(self, holding: PortfolioHolding) -> PortfolioHolding:
        insert_stmt = pg_insert(PortfolioHoldingORM).values(
            holding_id=holding.holding_id,
            portfolio_id=holding.portfolio_id,
            security_id=holding.security_id,
            quantity=holding.quantity,
            average_cost=holding.average_cost,
            cost_basis=holding.cost_basis,
            realized_pnl=holding.realized_pnl,
            first_acquired_at=holding.first_acquired_at,
            last_transaction_at=holding.last_transaction_at,
        )
        statement = insert_stmt.on_conflict_do_update(
            constraint="uq_portfolio_holdings_portfolio_security",
            set_={
                "quantity": insert_stmt.excluded.quantity,
                "average_cost": insert_stmt.excluded.average_cost,
                "cost_basis": insert_stmt.excluded.cost_basis,
                "realized_pnl": insert_stmt.excluded.realized_pnl,
                "last_transaction_at": insert_stmt.excluded.last_transaction_at,
                "updated_at": func.now(),
            },
        ).returning(PortfolioHoldingORM.holding_id)
        result = await self._session.execute(statement)
        canonical_id = result.scalar_one()
        row = await self._session.get(PortfolioHoldingORM, canonical_id)
        assert row is not None
        return portfolio_holding_orm_to_domain(row)

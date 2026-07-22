"""SQLAlchemy repository for `PortfolioValuationSnapshot` / `PortfolioPositionValuation` persistence.

`portfolio_valuation_snapshots` is a TimescaleDB hypertable; see the
module docstring in `orm/portfolio_valuation_snapshot.py` for why its
primary key is `(snapshot_id, as_of)` and why child position-valuation
rows reference `snapshot_id` without a DB-level foreign key.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from stock_research_core.domain.virtual_portfolio.models import (
    PortfolioPositionValuation,
    PortfolioValuationSnapshot,
)
from stock_research_core.infrastructure.database.mappers.virtual_portfolio_mappers import (
    portfolio_position_valuation_orm_to_domain,
    portfolio_valuation_snapshot_orm_to_domain,
)
from stock_research_core.infrastructure.database.orm.portfolio_position_valuation import (
    PortfolioPositionValuationORM,
)
from stock_research_core.infrastructure.database.orm.portfolio_valuation_snapshot import (
    PortfolioValuationSnapshotORM,
)

_SNAPSHOT_UPDATE_COLUMNS = [
    "data_cutoff_at",
    "cash_balance",
    "holdings_value",
    "total_value",
    "total_cost_basis",
    "realized_pnl",
    "unrealized_pnl",
    "net_profit",
    "total_return",
    "benchmark_return",
    "excess_return",
    "largest_position_weight",
    "largest_sector_weight",
    "cash_weight",
    "position_count",
    "portfolio_hhi",
    "sector_hhi",
    "diversification_score",
]

_POSITION_UPDATE_COLUMNS = [
    "quantity",
    "market_price",
    "market_value",
    "average_cost",
    "cost_basis",
    "unrealized_pnl",
    "unrealized_return",
    "portfolio_weight",
    "sector",
    "price_timestamp",
]


class SqlAlchemyPortfolioValuationRepository:
    """Persists and queries `PortfolioValuationSnapshot` and `PortfolioPositionValuation` rows."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_snapshot(self, snapshot: PortfolioValuationSnapshot) -> PortfolioValuationSnapshot:
        insert_stmt = pg_insert(PortfolioValuationSnapshotORM).values(
            snapshot_id=snapshot.snapshot_id,
            portfolio_id=snapshot.portfolio_id,
            as_of=snapshot.as_of,
            data_cutoff_at=snapshot.data_cutoff_at,
            cash_balance=snapshot.cash_balance,
            holdings_value=snapshot.holdings_value,
            total_value=snapshot.total_value,
            total_cost_basis=snapshot.total_cost_basis,
            realized_pnl=snapshot.realized_pnl,
            unrealized_pnl=snapshot.unrealized_pnl,
            net_profit=snapshot.net_profit,
            total_return=snapshot.total_return,
            benchmark_return=snapshot.benchmark_return,
            excess_return=snapshot.excess_return,
            largest_position_weight=snapshot.largest_position_weight,
            largest_sector_weight=snapshot.largest_sector_weight,
            cash_weight=snapshot.cash_weight,
            position_count=snapshot.position_count,
            portfolio_hhi=snapshot.portfolio_hhi,
            sector_hhi=snapshot.sector_hhi,
            diversification_score=snapshot.diversification_score,
            valuation_version=snapshot.valuation_version,
        )
        statement = insert_stmt.on_conflict_do_update(
            constraint="uq_portfolio_valuation_snapshots_portfolio_as_of_version",
            set_={
                column: getattr(insert_stmt.excluded, column) for column in _SNAPSHOT_UPDATE_COLUMNS
            }
            | {"updated_at": func.now()},
        ).returning(PortfolioValuationSnapshotORM.snapshot_id, PortfolioValuationSnapshotORM.as_of)
        result = await self._session.execute(statement)
        canonical_id, canonical_as_of = result.one()
        row = await self._session.get(PortfolioValuationSnapshotORM, (canonical_id, canonical_as_of))
        assert row is not None
        return portfolio_valuation_snapshot_orm_to_domain(row)

    async def upsert_positions(
        self, positions: list[PortfolioPositionValuation]
    ) -> list[PortfolioPositionValuation]:
        if not positions:
            return []
        results = []
        for position in positions:
            insert_stmt = pg_insert(PortfolioPositionValuationORM).values(
                position_valuation_id=position.position_valuation_id,
                snapshot_id=position.snapshot_id,
                portfolio_id=position.portfolio_id,
                security_id=position.security_id,
                quantity=position.quantity,
                market_price=position.market_price,
                market_value=position.market_value,
                average_cost=position.average_cost,
                cost_basis=position.cost_basis,
                unrealized_pnl=position.unrealized_pnl,
                unrealized_return=position.unrealized_return,
                portfolio_weight=position.portfolio_weight,
                sector=position.sector,
                price_timestamp=position.price_timestamp,
            )
            statement = insert_stmt.on_conflict_do_update(
                constraint="uq_portfolio_position_valuations_snapshot_security",
                set_={
                    column: getattr(insert_stmt.excluded, column) for column in _POSITION_UPDATE_COLUMNS
                },
            ).returning(PortfolioPositionValuationORM.position_valuation_id)
            result = await self._session.execute(statement)
            canonical_id = result.scalar_one()
            row = await self._session.get(PortfolioPositionValuationORM, canonical_id)
            assert row is not None
            results.append(portfolio_position_valuation_orm_to_domain(row))
        return results

    async def get_latest(self, portfolio_id: UUID) -> PortfolioValuationSnapshot | None:
        statement = (
            select(PortfolioValuationSnapshotORM)
            .where(PortfolioValuationSnapshotORM.portfolio_id == portfolio_id)
            .order_by(PortfolioValuationSnapshotORM.as_of.desc())
            .limit(1)
        )
        result = await self._session.execute(statement)
        row = result.scalars().first()
        return portfolio_valuation_snapshot_orm_to_domain(row) if row is not None else None

    async def get_by_as_of(
        self, portfolio_id: UUID, as_of: datetime, valuation_version: str
    ) -> PortfolioValuationSnapshot | None:
        statement = select(PortfolioValuationSnapshotORM).where(
            PortfolioValuationSnapshotORM.portfolio_id == portfolio_id,
            PortfolioValuationSnapshotORM.as_of == as_of,
            PortfolioValuationSnapshotORM.valuation_version == valuation_version,
        )
        result = await self._session.execute(statement)
        row = result.scalars().first()
        return portfolio_valuation_snapshot_orm_to_domain(row) if row is not None else None

    async def list_range(
        self, portfolio_id: UUID, start_at: datetime, end_at: datetime
    ) -> list[PortfolioValuationSnapshot]:
        statement = (
            select(PortfolioValuationSnapshotORM)
            .where(
                PortfolioValuationSnapshotORM.portfolio_id == portfolio_id,
                PortfolioValuationSnapshotORM.as_of >= start_at,
                PortfolioValuationSnapshotORM.as_of <= end_at,
            )
            .order_by(PortfolioValuationSnapshotORM.as_of.asc())
        )
        result = await self._session.execute(statement)
        return [portfolio_valuation_snapshot_orm_to_domain(row) for row in result.scalars().all()]

    async def list_positions(self, snapshot_id: UUID) -> list[PortfolioPositionValuation]:
        statement = (
            select(PortfolioPositionValuationORM)
            .where(PortfolioPositionValuationORM.snapshot_id == snapshot_id)
            .order_by(PortfolioPositionValuationORM.security_id.asc())
        )
        result = await self._session.execute(statement)
        return [portfolio_position_valuation_orm_to_domain(row) for row in result.scalars().all()]

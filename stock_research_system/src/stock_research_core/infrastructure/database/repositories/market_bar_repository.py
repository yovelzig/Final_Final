"""SQLAlchemy repository for bulk-upserting and querying `MarketBar` rows.

`market_bars` is converted into a TimescaleDB hypertable by migration;
this repository only ever deals with plain SQL against it.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from stock_research_core.application.exceptions import PersistenceError
from stock_research_core.domain.models import MarketBar
from stock_research_core.infrastructure.database.mappers.market_bar_mapper import (
    market_bar_orm_to_domain,
)
from stock_research_core.infrastructure.database.orm.market_bar import MarketBarORM

_CONFLICT_COLUMNS = ["security_id", "timestamp", "interval", "source_name"]


class SqlAlchemyMarketBarRepository:
    """Bulk-upserts and queries `MarketBar` rows."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_many(self, bars: list[MarketBar]) -> int:
        if not bars:
            return 0

        values = [
            {
                "security_id": bar.security_id,
                "timestamp": bar.timestamp,
                "interval": bar.interval,
                "source_name": bar.source_name,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "adjusted_close": bar.adjusted_close,
                "volume": bar.volume,
            }
            for bar in bars
        ]

        insert_stmt = pg_insert(MarketBarORM).values(values)
        statement = insert_stmt.on_conflict_do_update(
            index_elements=_CONFLICT_COLUMNS,
            set_={
                "open": insert_stmt.excluded.open,
                "high": insert_stmt.excluded.high,
                "low": insert_stmt.excluded.low,
                "close": insert_stmt.excluded.close,
                "adjusted_close": insert_stmt.excluded.adjusted_close,
                "volume": insert_stmt.excluded.volume,
                "updated_at": func.now(),
            },
        )

        try:
            await self._session.execute(statement)
        except IntegrityError as exc:
            raise PersistenceError(
                "Failed to upsert market bars: one or more bars reference a "
                "security that does not exist in the database."
            ) from exc

        return len(bars)

    async def list_range(
        self,
        security_id: UUID,
        start_at: datetime,
        end_at: datetime,
        interval: str = "1d",
        source_name: str | None = None,
    ) -> list[MarketBar]:
        statement = (
            select(MarketBarORM)
            .where(MarketBarORM.security_id == security_id)
            .where(MarketBarORM.interval == interval)
            .where(MarketBarORM.timestamp >= start_at)
            .where(MarketBarORM.timestamp <= end_at)
        )
        if source_name is not None:
            statement = statement.where(MarketBarORM.source_name == source_name)
        statement = statement.order_by(MarketBarORM.timestamp.asc())

        result = await self._session.execute(statement)
        return [market_bar_orm_to_domain(row) for row in result.scalars().all()]

    async def get_latest_timestamp(
        self,
        security_id: UUID,
        interval: str = "1d",
        source_name: str | None = None,
    ) -> datetime | None:
        statement = select(func.max(MarketBarORM.timestamp)).where(
            MarketBarORM.security_id == security_id,
            MarketBarORM.interval == interval,
        )
        if source_name is not None:
            statement = statement.where(MarketBarORM.source_name == source_name)
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def count(self, security_id: UUID, interval: str = "1d") -> int:
        statement = (
            select(func.count())
            .select_from(MarketBarORM)
            .where(MarketBarORM.security_id == security_id, MarketBarORM.interval == interval)
        )
        result = await self._session.execute(statement)
        return int(result.scalar_one())

    async def get_next_bar_after(
        self,
        security_id: UUID,
        after_at: datetime,
        interval: str = "1d",
        source_name: str | None = None,
    ) -> MarketBar | None:
        statement = (
            select(MarketBarORM)
            .where(MarketBarORM.security_id == security_id)
            .where(MarketBarORM.interval == interval)
            .where(MarketBarORM.timestamp > after_at)
        )
        if source_name is not None:
            statement = statement.where(MarketBarORM.source_name == source_name)
        statement = statement.order_by(MarketBarORM.timestamp.asc()).limit(1)

        result = await self._session.execute(statement)
        row = result.scalars().first()
        return market_bar_orm_to_domain(row) if row is not None else None

    async def get_latest_bar_at_or_before(
        self,
        security_id: UUID,
        as_of: datetime,
        interval: str = "1d",
        source_name: str | None = None,
    ) -> MarketBar | None:
        statement = (
            select(MarketBarORM)
            .where(MarketBarORM.security_id == security_id)
            .where(MarketBarORM.interval == interval)
            .where(MarketBarORM.timestamp <= as_of)
        )
        if source_name is not None:
            statement = statement.where(MarketBarORM.source_name == source_name)
        statement = statement.order_by(MarketBarORM.timestamp.desc()).limit(1)

        result = await self._session.execute(statement)
        row = result.scalars().first()
        return market_bar_orm_to_domain(row) if row is not None else None

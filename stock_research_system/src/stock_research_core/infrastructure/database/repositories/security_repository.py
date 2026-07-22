"""SQLAlchemy repository for `Security` persistence.

Canonical key is `(ticker, exchange)`: on conflict, the already-stored
`security_id` is preserved and the row is updated in place, so a
provider-created domain object with a different UUID never creates a
duplicate row.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from stock_research_core.domain.enums import Exchange
from stock_research_core.domain.models import Security
from stock_research_core.infrastructure.database.mappers.security_mapper import (
    security_orm_to_domain,
)
from stock_research_core.infrastructure.database.orm.security import SecurityORM


class SqlAlchemySecurityRepository:
    """Persists and retrieves `Security` rows."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, security: Security) -> Security:
        insert_stmt = pg_insert(SecurityORM).values(
            security_id=security.security_id,
            ticker=security.ticker,
            company_name=security.company_name,
            exchange=security.exchange.value,
            currency=security.currency,
            sector=security.sector,
            industry=security.industry,
            active=security.active,
        )
        statement = insert_stmt.on_conflict_do_update(
            constraint="uq_securities_ticker_exchange",
            set_={
                "company_name": insert_stmt.excluded.company_name,
                "currency": insert_stmt.excluded.currency,
                "sector": insert_stmt.excluded.sector,
                "industry": insert_stmt.excluded.industry,
                "active": insert_stmt.excluded.active,
                "updated_at": func.now(),
            },
        ).returning(SecurityORM.security_id)

        result = await self._session.execute(statement)
        canonical_id = result.scalar_one()

        row = await self._session.get(SecurityORM, canonical_id)
        assert row is not None
        return security_orm_to_domain(row)

    async def get_by_id(self, security_id: UUID) -> Security | None:
        row = await self._session.get(SecurityORM, security_id)
        return security_orm_to_domain(row) if row is not None else None

    async def get_by_ticker(
        self, ticker: str, exchange: Exchange | None = None
    ) -> Security | None:
        statement = select(SecurityORM).where(SecurityORM.ticker == ticker.strip().upper())
        if exchange is not None:
            statement = statement.where(SecurityORM.exchange == exchange.value)
        result = await self._session.execute(statement)
        row = result.scalars().first()
        return security_orm_to_domain(row) if row is not None else None

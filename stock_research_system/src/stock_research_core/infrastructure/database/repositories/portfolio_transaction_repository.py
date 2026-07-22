"""SQLAlchemy repository for `PortfolioTransaction` persistence."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from stock_research_core.application.exceptions import PersistenceError
from stock_research_core.domain.virtual_portfolio.models import PortfolioTransaction
from stock_research_core.infrastructure.database.mappers.virtual_portfolio_mappers import (
    portfolio_transaction_orm_to_domain,
)
from stock_research_core.infrastructure.database.orm.portfolio_transaction import PortfolioTransactionORM


class SqlAlchemyPortfolioTransactionRepository:
    """Persists and queries `PortfolioTransaction` rows."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_pending(self, transaction: PortfolioTransaction) -> PortfolioTransaction:
        row = PortfolioTransactionORM(
            transaction_id=transaction.transaction_id,
            portfolio_id=transaction.portfolio_id,
            security_id=transaction.security_id,
            transaction_type=transaction.transaction_type.value,
            status=transaction.status.value,
            requested_at=transaction.requested_at,
            executed_at=transaction.executed_at,
            requested_quantity=transaction.requested_quantity,
            executed_quantity=transaction.executed_quantity,
            execution_price=transaction.execution_price,
            gross_amount=transaction.gross_amount,
            fee_amount=transaction.fee_amount,
            net_cash_effect=transaction.net_cash_effect,
            source_name=transaction.source_name,
            interval=transaction.interval,
            execution_rule_version=transaction.execution_rule_version,
            idempotency_key=transaction.idempotency_key,
            rejection_reason=(
                transaction.rejection_reason.value if transaction.rejection_reason is not None else None
            ),
            rejection_message=transaction.rejection_message,
        )
        self._session.add(row)
        await self._session.flush()
        return portfolio_transaction_orm_to_domain(row)

    async def get(self, transaction_id: UUID) -> PortfolioTransaction | None:
        row = await self._session.get(PortfolioTransactionORM, transaction_id)
        return portfolio_transaction_orm_to_domain(row) if row is not None else None

    async def get_by_idempotency_key(
        self, portfolio_id: UUID, idempotency_key: str
    ) -> PortfolioTransaction | None:
        statement = select(PortfolioTransactionORM).where(
            PortfolioTransactionORM.portfolio_id == portfolio_id,
            PortfolioTransactionORM.idempotency_key == idempotency_key,
        )
        result = await self._session.execute(statement)
        row = result.scalars().first()
        return portfolio_transaction_orm_to_domain(row) if row is not None else None

    async def mark_executed(self, transaction: PortfolioTransaction) -> PortfolioTransaction:
        row = await self._session.get(PortfolioTransactionORM, transaction.transaction_id)
        if row is None:
            raise PersistenceError(f"No portfolio transaction found with id '{transaction.transaction_id}'.")
        row.status = transaction.status.value
        row.executed_at = transaction.executed_at
        row.executed_quantity = transaction.executed_quantity
        row.execution_price = transaction.execution_price
        row.gross_amount = transaction.gross_amount
        row.fee_amount = transaction.fee_amount
        row.net_cash_effect = transaction.net_cash_effect
        await self._session.flush()
        await self._session.refresh(row)
        return portfolio_transaction_orm_to_domain(row)

    async def mark_rejected(self, transaction: PortfolioTransaction) -> PortfolioTransaction:
        row = await self._session.get(PortfolioTransactionORM, transaction.transaction_id)
        if row is None:
            raise PersistenceError(f"No portfolio transaction found with id '{transaction.transaction_id}'.")
        row.status = transaction.status.value
        row.rejection_reason = (
            transaction.rejection_reason.value if transaction.rejection_reason is not None else None
        )
        row.rejection_message = transaction.rejection_message
        await self._session.flush()
        await self._session.refresh(row)
        return portfolio_transaction_orm_to_domain(row)

    async def list_for_portfolio(
        self,
        portfolio_id: UUID,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> list[PortfolioTransaction]:
        statement = select(PortfolioTransactionORM).where(
            PortfolioTransactionORM.portfolio_id == portfolio_id
        )
        if start_at is not None:
            statement = statement.where(PortfolioTransactionORM.requested_at >= start_at)
        if end_at is not None:
            statement = statement.where(PortfolioTransactionORM.requested_at <= end_at)
        statement = statement.order_by(PortfolioTransactionORM.requested_at.asc())
        result = await self._session.execute(statement)
        return [portfolio_transaction_orm_to_domain(row) for row in result.scalars().all()]

"""ORM model for the `portfolio_transactions` table."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class PortfolioTransactionORM(Base):
    """One simulated buy or sell trade, from request through execution/rejection."""

    __tablename__ = "portfolio_transactions"
    __table_args__ = (
        UniqueConstraint("portfolio_id", "idempotency_key", name="uq_portfolio_transactions_idempotency"),
        Index("ix_portfolio_transactions_portfolio_requested", "portfolio_id", "requested_at"),
        Index("ix_portfolio_transactions_security_executed", "security_id", "executed_at"),
        Index("ix_portfolio_transactions_status", "status"),
    )

    transaction_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("virtual_portfolios.portfolio_id", ondelete="RESTRICT"),
        nullable=False,
    )
    security_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("securities.security_id", ondelete="RESTRICT"), nullable=False
    )

    transaction_type: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)

    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    requested_quantity: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    executed_quantity: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)

    execution_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    gross_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    fee_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    net_cash_effect: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)

    source_name: Mapped[str] = mapped_column(String(250), nullable=False)
    interval: Mapped[str] = mapped_column(String(20), nullable=False)
    execution_rule_version: Mapped[str] = mapped_column(String(50), nullable=False)

    idempotency_key: Mapped[str] = mapped_column(String(250), nullable=False)
    rejection_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)
    rejection_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

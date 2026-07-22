"""ORM model for the `portfolio_holdings` table."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class PortfolioHoldingORM(Base):
    """A portfolio's current position in one security. Unique per (portfolio, security)."""

    __tablename__ = "portfolio_holdings"
    __table_args__ = (
        UniqueConstraint("portfolio_id", "security_id", name="uq_portfolio_holdings_portfolio_security"),
        Index("ix_portfolio_holdings_portfolio_id", "portfolio_id"),
        Index("ix_portfolio_holdings_updated_at", "updated_at"),
    )

    holding_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("virtual_portfolios.portfolio_id", ondelete="RESTRICT"),
        nullable=False,
    )
    security_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("securities.security_id", ondelete="RESTRICT"), nullable=False
    )

    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    average_cost: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    cost_basis: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    realized_pnl: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False, default=0)

    first_acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_transaction_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

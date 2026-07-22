"""ORM model for the `virtual_portfolios` table."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class VirtualPortfolioORM(Base):
    """One learner's educational, simulated investment portfolio."""

    __tablename__ = "virtual_portfolios"
    __table_args__ = (
        Index("ix_virtual_portfolios_learner_status", "learner_id", "status"),
        Index("ix_virtual_portfolios_current_simulation_at", "current_simulation_at"),
    )

    portfolio_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    learner_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("learner_profiles.learner_id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    base_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    initial_cash: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    cash_balance: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)

    benchmark_security_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("securities.security_id", ondelete="RESTRICT"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)

    allow_fractional_shares: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    require_decision_journal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    fixed_transaction_fee: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False, default=0)
    transaction_fee_bps: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False, default=0)

    simulation_start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    current_simulation_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    portfolio_version: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

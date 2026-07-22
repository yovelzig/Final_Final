"""ORM model for the `portfolio_valuation_runs` table."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class PortfolioValuationRunORM(Base):
    """An auditable record of one valuation calculation attempt."""

    __tablename__ = "portfolio_valuation_runs"
    __table_args__ = (
        Index("ix_portfolio_valuation_runs_portfolio_started", "portfolio_id", "started_at"),
        Index("ix_portfolio_valuation_runs_status", "status"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("virtual_portfolios.portfolio_id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    requested_as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valuation_version: Mapped[str] = mapped_column(String(50), nullable=False)
    risk_policy_version: Mapped[str] = mapped_column(String(50), nullable=False)

    holding_count: Mapped[int] = mapped_column(Integer, nullable=False)
    priced_holding_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    missing_price_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    error_type: Mapped[str | None] = mapped_column(String(250), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

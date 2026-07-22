"""ORM model for the `portfolio_position_valuations` table.

`snapshot_id` is a plain, indexed UUID column - not a foreign key. See
the module docstring in `portfolio_valuation_snapshot.py` for why: a
hypertable's primary key must include its partitioning column
(`as_of`), so a child table cannot declare a simple FK to `snapshot_id`
alone. Referential integrity to `portfolio_valuation_snapshots` is
enforced at the application layer.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class PortfolioPositionValuationORM(Base):
    """One holding's valuation as of a `PortfolioValuationSnapshot`."""

    __tablename__ = "portfolio_position_valuations"
    __table_args__ = (
        UniqueConstraint(
            "snapshot_id", "security_id", name="uq_portfolio_position_valuations_snapshot_security"
        ),
        Index("ix_portfolio_position_valuations_snapshot_id", "snapshot_id"),
        Index("ix_portfolio_position_valuations_portfolio_id", "portfolio_id"),
    )

    position_valuation_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("virtual_portfolios.portfolio_id", ondelete="RESTRICT"),
        nullable=False,
    )
    security_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("securities.security_id", ondelete="RESTRICT"), nullable=False
    )

    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    market_price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    market_value: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)

    average_cost: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    cost_basis: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    unrealized_pnl: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    unrealized_return: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)

    portfolio_weight: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    sector: Mapped[str | None] = mapped_column(String(250), nullable=True)

    price_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

"""ORM model for the `portfolio_valuation_snapshots` hypertable.

Converted into a TimescaleDB hypertable (partitioned by `as_of`) by
migration. TimescaleDB requires every unique/primary-key constraint on
a hypertable to include the partitioning column, so the primary key
here is `(snapshot_id, as_of)` rather than `snapshot_id` alone - the
natural business key `(portfolio_id, as_of, valuation_version)` is a
second unique constraint, which also includes `as_of` and is therefore
compatible.

Because of this, child tables (`portfolio_position_valuations`,
`portfolio_risk_assessments`) cannot declare a plain foreign key to
`snapshot_id` alone (Postgres requires a `FOREIGN KEY` to reference a
full unique constraint on the parent, and one that also includes
`as_of` would require duplicating `as_of` onto every child row). Those
tables store `snapshot_id` as a plain, indexed UUID column instead,
with referential integrity enforced at the application layer - a
well-known, documented TimescaleDB limitation, not an oversight.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class PortfolioValuationSnapshotORM(Base):
    """A point-in-time valuation of an entire portfolio."""

    __tablename__ = "portfolio_valuation_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "portfolio_id",
            "as_of",
            "valuation_version",
            name="uq_portfolio_valuation_snapshots_portfolio_as_of_version",
        ),
        Index("ix_portfolio_valuation_snapshots_portfolio_as_of", "portfolio_id", "as_of"),
        Index("ix_portfolio_valuation_snapshots_valuation_version", "valuation_version"),
    )

    snapshot_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("virtual_portfolios.portfolio_id", ondelete="RESTRICT"),
        nullable=False,
    )
    data_cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    cash_balance: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    holdings_value: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    total_value: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)

    total_cost_basis: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    realized_pnl: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    unrealized_pnl: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)

    net_profit: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    total_return: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)

    benchmark_return: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    excess_return: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)

    largest_position_weight: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    largest_sector_weight: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    cash_weight: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    position_count: Mapped[int] = mapped_column(Integer, nullable=False)

    portfolio_hhi: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    sector_hhi: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    diversification_score: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)

    valuation_version: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

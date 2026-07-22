"""ORM model for the `market_bars` hypertable.

The primary key (`security_id`, `timestamp`, `interval`, `source_name`)
deliberately includes the time-partitioning column (`timestamp`) so it
is compatible with a TimescaleDB hypertable, whose unique constraints
must all include the partitioning column.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class MarketBarORM(Base):
    """A single OHLCV bar. Converted into a TimescaleDB hypertable by migration."""

    __tablename__ = "market_bars"
    __table_args__ = (
        Index("ix_market_bars_security_timestamp", "security_id", "timestamp"),
        Index(
            "ix_market_bars_security_interval_timestamp",
            "security_id",
            "interval",
            "timestamp",
        ),
        Index("ix_market_bars_timestamp", "timestamp"),
    )

    security_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("securities.security_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    interval: Mapped[str] = mapped_column(String(20), primary_key=True)
    source_name: Mapped[str] = mapped_column(String(250), primary_key=True)
    open: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    adjusted_close: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

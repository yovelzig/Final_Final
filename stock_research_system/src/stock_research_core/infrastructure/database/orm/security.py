"""ORM model for the `securities` table."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class SecurityORM(Base):
    """Canonical stored security. `ticker`+`exchange` is the natural key."""

    __tablename__ = "securities"
    __table_args__ = (
        UniqueConstraint("ticker", "exchange", name="uq_securities_ticker_exchange"),
        Index("ix_securities_ticker", "ticker"),
        Index("ix_securities_active", "active"),
    )

    security_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    company_name: Mapped[str] = mapped_column(String(250), nullable=False)
    exchange: Mapped[str] = mapped_column(String(30), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    sector: Mapped[str | None] = mapped_column(String(250), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(250), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

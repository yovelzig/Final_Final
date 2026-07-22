"""ORM model for the `tracked_securities` table."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Numeric, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class TrackedSecurityORM(Base):
    """A security under ongoing monitoring. Maps to the domain `TrackedSecurity`."""

    __tablename__ = "tracked_securities"
    __table_args__ = (
        Index("ix_tracked_securities_enabled", "enabled"),
        Index("ix_tracked_securities_next_scheduled_update_at", "next_scheduled_update_at"),
    )

    security_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("securities.security_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    monitoring_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_successful_update_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_scheduled_update_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    alert_threshold_probability_change: Mapped[Decimal] = mapped_column(
        Numeric(8, 6), nullable=False
    )
    alert_threshold_expected_return_change: Mapped[Decimal] = mapped_column(
        Numeric(8, 6), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

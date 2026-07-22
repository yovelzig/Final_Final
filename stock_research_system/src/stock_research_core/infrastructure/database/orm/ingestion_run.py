"""ORM model for the `market_data_ingestion_runs` audit table."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from stock_research_core.infrastructure.database.base import Base
from stock_research_core.infrastructure.database.orm.quality_issue import (
    MarketDataQualityIssueORM,
)


class MarketDataIngestionRunORM(Base):
    """An audit record of one ingestion attempt for a security."""

    __tablename__ = "market_data_ingestion_runs"
    __table_args__ = (
        Index("ix_ingestion_runs_security_started", "security_id", "started_at"),
        Index("ix_ingestion_runs_status", "status"),
        Index("ix_ingestion_runs_provider_name", "provider_name"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    security_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("securities.security_id", ondelete="RESTRICT"),
        nullable=False,
    )
    provider_name: Mapped[str] = mapped_column(String(250), nullable=False)
    interval: Mapped[str] = mapped_column(String(20), nullable=False)
    requested_start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    requested_end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_incremental: Mapped[bool] = mapped_column(Boolean, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    provider_rows_received: Mapped[int] = mapped_column(Integer, nullable=False)
    valid_bars_returned: Mapped[int] = mapped_column(Integer, nullable=False)
    bars_persisted: Mapped[int] = mapped_column(Integer, nullable=False)
    duplicate_rows_removed: Mapped[int] = mapped_column(Integer, nullable=False)
    invalid_rows_removed: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(250), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    quality_issues: Mapped[list[MarketDataQualityIssueORM]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )

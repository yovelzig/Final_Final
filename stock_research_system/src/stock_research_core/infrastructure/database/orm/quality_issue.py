"""ORM model for the `market_data_quality_issues` table."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from stock_research_core.infrastructure.database.base import Base

if TYPE_CHECKING:
    from stock_research_core.infrastructure.database.orm.ingestion_run import (
        MarketDataIngestionRunORM,
    )


class MarketDataQualityIssueORM(Base):
    """A single data-quality observation belonging to an ingestion run."""

    __tablename__ = "market_data_quality_issues"
    __table_args__ = (
        Index("ix_quality_issues_run_id", "run_id"),
        Index("ix_quality_issues_code", "code"),
        Index("ix_quality_issues_severity", "severity"),
    )

    issue_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("market_data_ingestion_runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    run: Mapped["MarketDataIngestionRunORM"] = relationship(back_populates="quality_issues")

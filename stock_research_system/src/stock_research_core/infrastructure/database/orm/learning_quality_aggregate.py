"""ORM model for the `learning_quality_aggregates` table (Phase 13)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class LearningQualityAggregateORM(Base):
    __tablename__ = "learning_quality_aggregates"
    __table_args__ = (
        UniqueConstraint(
            "metric_type", "period_start", "period_end", "cohort_key", "calculation_version", "filter_hash",
            name="uq_learning_quality_aggregates_identity",
        ),
        Index("ix_learning_quality_aggregates_metric_period", "metric_type", "period_start"),
    )

    aggregate_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    metric_type: Mapped[str] = mapped_column(String(48), nullable=False)

    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    cohort_key: Mapped[str] = mapped_column(String(200), nullable=False)
    cohort_size: Mapped[int] = mapped_column(Integer, nullable=False)

    value: Mapped[float] = mapped_column(Float, nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)

    calculation_version: Mapped[str] = mapped_column(String(50), nullable=False)
    filters: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    filter_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

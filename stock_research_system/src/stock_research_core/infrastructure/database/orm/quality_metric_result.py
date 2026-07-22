"""ORM model for the `quality_metric_results` table (Phase 13)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class QualityMetricResultORM(Base):
    __tablename__ = "quality_metric_results"
    __table_args__ = (Index("ix_quality_metric_results_run_metric", "run_id", "metric_name"),)

    metric_result_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("quality_evaluation_runs.run_id", ondelete="CASCADE"), nullable=False
    )
    sample_result_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("quality_evaluation_sample_results.sample_result_id", ondelete="CASCADE"),
        nullable=True,
    )

    metric_name: Mapped[str] = mapped_column(String(100), nullable=False)
    metric_type: Mapped[str] = mapped_column(String(24), nullable=False)
    metric_version: Mapped[str] = mapped_column(String(50), nullable=False)

    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    threshold: Mapped[float | None] = mapped_column(Float, nullable=True)

    details: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    evaluator_provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    evaluator_model: Mapped[str | None] = mapped_column(String(100), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

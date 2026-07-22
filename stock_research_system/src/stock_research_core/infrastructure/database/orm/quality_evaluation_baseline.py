"""ORM model for the `quality_evaluation_baselines` table (Phase 13)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class QualityEvaluationBaselineORM(Base):
    __tablename__ = "quality_evaluation_baselines"
    __table_args__ = (Index("ix_quality_evaluation_baselines_suite_approved", "suite_id", "approved"),)

    baseline_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    suite_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("quality_evaluation_suites.suite_id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("quality_evaluation_runs.run_id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    approved: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    approved_by_account_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("user_accounts.account_id", ondelete="SET NULL"), nullable=True
    )

    metric_summary: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    safety_gate_summary: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

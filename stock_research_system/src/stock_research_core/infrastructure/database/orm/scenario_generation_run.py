"""ORM model for the `scenario_generation_runs` audit table."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class ScenarioGenerationRunORM(Base):
    """An auditable record of one attempt to generate/validate a scenario
    (typically from `scripts/seed_historical_market_scenarios.py`)."""

    __tablename__ = "scenario_generation_runs"
    __table_args__ = (
        Index("ix_scenario_generation_runs_status", "status"),
        Index("ix_scenario_generation_runs_started_at", "started_at"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    focal_security_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("securities.security_id", ondelete="RESTRICT"), nullable=False
    )
    benchmark_security_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("securities.security_id", ondelete="RESTRICT"), nullable=True
    )

    requested_observation_start_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    requested_decision_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    requested_reveal_end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    scenario_code: Mapped[str] = mapped_column(String(150), nullable=False)
    scenario_version: Mapped[str] = mapped_column(String(50), nullable=False)

    observation_bars_found: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reveal_bars_found: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    benchmark_bars_found: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(200), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

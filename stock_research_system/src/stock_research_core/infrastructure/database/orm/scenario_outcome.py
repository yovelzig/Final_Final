"""ORM model for the `scenario_outcomes` table.

Never stores raw price bars again - only the derived, versioned outcome
metrics computed from bars already stored in `market_bars`.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class ScenarioOutcomeORM(Base):
    """The realized future outcome of a scenario, computed once per
    calculation version and reused across `reveal_outcome`/`get_reveal`."""

    __tablename__ = "scenario_outcomes"
    __table_args__ = (
        UniqueConstraint(
            "scenario_id", "calculation_version", name="uq_scenario_outcomes_scenario_version"
        ),
        CheckConstraint(
            "maximum_future_upside >= 0", name="ck_scenario_outcomes_max_upside_nonneg"
        ),
        CheckConstraint(
            "maximum_future_drawdown <= 0", name="ck_scenario_outcomes_max_drawdown_nonpos"
        ),
    )

    outcome_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    scenario_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("historical_market_scenarios.scenario_id", ondelete="CASCADE"),
        nullable=False,
    )
    decision_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reveal_end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    focal_start_close: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    focal_end_close: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    focal_return: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    maximum_future_upside: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    maximum_future_drawdown: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)

    benchmark_return: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    excess_return: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)

    outcome_direction: Mapped[str] = mapped_column(String(20), nullable=False)
    outcome_summary: Mapped[str] = mapped_column(Text, nullable=False)

    calculation_version: Mapped[str] = mapped_column(String(50), nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

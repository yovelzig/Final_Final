"""ORM model for the `scenario_securities` table - the source of truth
for a scenario's focal and (optional) benchmark security."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class ScenarioSecurityORM(Base):
    """One (scenario, security, role) row."""

    __tablename__ = "scenario_securities"
    __table_args__ = (
        UniqueConstraint("scenario_id", "role", name="uq_scenario_securities_scenario_role"),
        UniqueConstraint("scenario_id", "security_id", name="uq_scenario_securities_scenario_security"),
        CheckConstraint("role IN ('FOCAL', 'BENCHMARK')", name="ck_scenario_securities_role"),
    )

    scenario_security_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    scenario_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("historical_market_scenarios.scenario_id", ondelete="CASCADE"),
        nullable=False,
    )
    security_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("securities.security_id", ondelete="RESTRICT"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

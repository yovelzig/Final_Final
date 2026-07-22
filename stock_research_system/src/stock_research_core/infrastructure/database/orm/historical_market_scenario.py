"""ORM models for `historical_market_scenarios` and its two skill
association tables.

`learning_objectives` is stored as a native Postgres array, not a
table: soft, auxiliary metadata (a list of English sentences), the same
treatment `ExerciseAdaptiveProfileORM.policy_tags` already gets, not one
of the core relationships spec section 15 calls out for normalization.
`focal_security_id`/`benchmark_security_id` deliberately do *not* live
here - `ScenarioSecurityORM` (see `scenario_security.py`) is the source
of truth, mirroring `LessonSecondarySkillORM` living apart from
`lessons`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class HistoricalMarketScenarioORM(Base):
    """A real historical period presented to a learner as a point-in-time
    decision exercise."""

    __tablename__ = "historical_market_scenarios"
    __table_args__ = (
        UniqueConstraint("code", name="uq_historical_market_scenarios_code"),
        UniqueConstraint("exercise_id", name="uq_historical_market_scenarios_exercise_id"),
        Index("ix_historical_market_scenarios_scenario_type", "scenario_type"),
        Index("ix_historical_market_scenarios_status", "status"),
        CheckConstraint(
            "observation_start_at < decision_at AND decision_at < reveal_end_at",
            name="ck_historical_market_scenarios_timestamp_order",
        ),
        CheckConstraint(
            "minimum_observation_bars >= 5", name="ck_historical_market_scenarios_min_observation_bars"
        ),
        CheckConstraint(
            "minimum_reveal_bars >= 1", name="ck_historical_market_scenarios_min_reveal_bars"
        ),
    )

    scenario_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    exercise_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("exercises.exercise_id", ondelete="RESTRICT"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(150), nullable=False)
    title: Mapped[str] = mapped_column(String(250), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    scenario_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)

    observation_start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decision_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reveal_end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    interval: Mapped[str] = mapped_column(String(20), nullable=False)
    source_name: Mapped[str] = mapped_column(String(250), nullable=False)

    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    learner_instructions: Mapped[str] = mapped_column(Text, nullable=False)
    learning_objectives: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)

    minimum_observation_bars: Mapped[int] = mapped_column(Integer, nullable=False)
    minimum_reveal_bars: Mapped[int] = mapped_column(Integer, nullable=False)

    scenario_version: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class HistoricalMarketScenarioPrimarySkillORM(Base):
    """Association table: a scenario's primary financial skills."""

    __tablename__ = "historical_market_scenario_primary_skills"

    scenario_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("historical_market_scenarios.scenario_id", ondelete="CASCADE"),
        primary_key=True,
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("financial_skills.skill_id", ondelete="RESTRICT"),
        primary_key=True,
    )


class HistoricalMarketScenarioSecondarySkillORM(Base):
    """Association table: a scenario's secondary financial skills."""

    __tablename__ = "historical_market_scenario_secondary_skills"

    scenario_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("historical_market_scenarios.scenario_id", ondelete="CASCADE"),
        primary_key=True,
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("financial_skills.skill_id", ondelete="RESTRICT"),
        primary_key=True,
    )

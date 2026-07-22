"""ORM models for `scenario_option_rubrics` and its feedback-code
association table."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base

_SCORE_COLUMNS = (
    "decision_quality_score",
    "risk_awareness_score",
    "benchmark_awareness_score",
    "horizon_alignment_score",
    "information_sufficiency_score",
    "uncertainty_awareness_score",
)


class ScenarioOptionRubricORM(Base):
    """The educational quality of selecting one `ExerciseOption`."""

    __tablename__ = "scenario_option_rubrics"
    __table_args__ = (
        UniqueConstraint(
            "scenario_id",
            "exercise_option_id",
            "rubric_version",
            name="uq_scenario_option_rubrics_scenario_option_version",
        ),
        *(
            CheckConstraint(
                f"{column} >= 0 AND {column} <= 1", name=f"ck_scenario_option_rubrics_{column}_range"
            )
            for column in _SCORE_COLUMNS
        ),
    )

    rubric_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    scenario_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("historical_market_scenarios.scenario_id", ondelete="CASCADE"),
        nullable=False,
    )
    exercise_option_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("exercise_options.option_id", ondelete="RESTRICT"),
        nullable=False,
    )
    decision_quality_score: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)

    risk_awareness_score: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    benchmark_awareness_score: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    horizon_alignment_score: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    information_sufficiency_score: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    uncertainty_awareness_score: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)

    expected_direction: Mapped[str] = mapped_column(String(30), nullable=False)

    positive_feedback: Mapped[str] = mapped_column(Text, nullable=False)
    improvement_feedback: Mapped[str] = mapped_column(Text, nullable=False)

    rubric_version: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ScenarioOptionRubricFeedbackCodeORM(Base):
    """Association table: the feedback codes attached to a rubric."""

    __tablename__ = "scenario_option_rubric_feedback_codes"

    rubric_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("scenario_option_rubrics.rubric_id", ondelete="CASCADE"),
        primary_key=True,
    )
    feedback_code: Mapped[str] = mapped_column(String(40), primary_key=True)

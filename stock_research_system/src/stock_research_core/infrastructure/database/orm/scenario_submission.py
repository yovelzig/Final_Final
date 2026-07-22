"""ORM models for `scenario_submissions` and its feedback-code
association table."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class ScenarioSubmissionORM(Base):
    """One learner's decision-and-reveal lifecycle for one scenario.
    Unique per `exercise_attempt_id` - a scenario attempt has exactly
    one submission.
    """

    __tablename__ = "scenario_submissions"
    __table_args__ = (
        UniqueConstraint(
            "exercise_attempt_id", name="uq_scenario_submissions_exercise_attempt_id"
        ),
        Index("ix_scenario_submissions_learner_created", "learner_id", "created_at"),
        Index("ix_scenario_submissions_scenario_created", "scenario_id", "created_at"),
    )

    submission_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    scenario_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("historical_market_scenarios.scenario_id", ondelete="RESTRICT"),
        nullable=False,
    )
    learner_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("learner_profiles.learner_id", ondelete="RESTRICT"),
        nullable=False,
    )
    exercise_attempt_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("exercise_attempts.attempt_id", ondelete="RESTRICT"),
        nullable=False,
    )
    selected_option_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("exercise_options.option_id", ondelete="RESTRICT"), nullable=True
    )

    status: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence_level: Mapped[str | None] = mapped_column(String(20), nullable=True)
    learner_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)

    decision_quality_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    outcome_alignment_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    total_display_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    decision_quality: Mapped[str | None] = mapped_column(String(20), nullable=True)

    feedback_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    reveal_status: Mapped[str] = mapped_column(String(20), nullable=False)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    graded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revealed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    rubric_version: Mapped[str] = mapped_column(String(50), nullable=False)
    outcome_calculation_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ScenarioSubmissionFeedbackCodeORM(Base):
    """Association table: the feedback codes attached to a submission."""

    __tablename__ = "scenario_submission_feedback_codes"

    submission_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("scenario_submissions.submission_id", ondelete="CASCADE"),
        primary_key=True,
    )
    feedback_code: Mapped[str] = mapped_column(String(40), primary_key=True)

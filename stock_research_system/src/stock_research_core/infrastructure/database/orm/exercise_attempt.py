"""ORM model for the `exercise_attempts` table."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class ExerciseAttemptORM(Base):
    """One learner's attempt at an exercise."""

    __tablename__ = "exercise_attempts"
    __table_args__ = (
        Index("ix_exercise_attempts_learner_exercise", "learner_id", "exercise_id"),
        Index("ix_exercise_attempts_learner_started", "learner_id", "started_at"),
        Index("ix_exercise_attempts_exercise_id", "exercise_id"),
    )

    attempt_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    learner_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("learner_profiles.learner_id", ondelete="RESTRICT"),
        nullable=False,
    )
    exercise_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("exercises.exercise_id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    graded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    score: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    maximum_score: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    is_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    confidence_level: Mapped[str | None] = mapped_column(String(20), nullable=True)
    response_time_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    grading_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

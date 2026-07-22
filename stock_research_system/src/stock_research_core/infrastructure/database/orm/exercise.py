"""ORM models for `exercises` and the `exercise_skills` association table."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class ExerciseORM(Base):
    """A gradeable exercise attached to a `Lesson`.

    `configuration` (JSONB) holds exercise-type-specific grading
    parameters (e.g. numeric tolerance); which skills an exercise
    practices is modeled as a real relation (`exercise_skills`), not JSON.
    """

    __tablename__ = "exercises"
    __table_args__ = (
        Index("ix_exercises_lesson_position", "lesson_id", "position"),
        Index("ix_exercises_exercise_type", "exercise_type"),
    )

    exercise_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    lesson_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("lessons.lesson_id", ondelete="CASCADE"), nullable=False
    )
    exercise_type: Mapped[str] = mapped_column(String(30), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    difficulty: Mapped[str] = mapped_column(String(20), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    maximum_score: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    passing_score: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    configuration: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ExerciseSkillORM(Base):
    """Association table: which skills an exercise practices."""

    __tablename__ = "exercise_skills"

    exercise_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("exercises.exercise_id", ondelete="CASCADE"),
        primary_key=True,
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("financial_skills.skill_id", ondelete="RESTRICT"),
        primary_key=True,
    )

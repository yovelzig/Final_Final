"""ORM models for `exercise_answers` and its two option-association tables.

`exercise_answer_selected_options` is an unordered set (SINGLE_CHOICE /
MULTIPLE_CHOICE / TRUE_FALSE); `exercise_answer_ordered_options` carries
an explicit `sequence_index` so a learner's submitted ordering
(ORDERING exercises) survives a round trip through the database.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class ExerciseAnswerORM(Base):
    """A learner's validated, submitted answer for one attempt."""

    __tablename__ = "exercise_answers"

    answer_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    attempt_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("exercise_attempts.attempt_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    numeric_answer: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    text_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ExerciseAnswerSelectedOptionORM(Base):
    """Association table: the (unordered) set of options a learner selected."""

    __tablename__ = "exercise_answer_selected_options"

    answer_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("exercise_answers.answer_id", ondelete="CASCADE"),
        primary_key=True,
    )
    option_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("exercise_options.option_id", ondelete="RESTRICT"),
        primary_key=True,
    )


class ExerciseAnswerOrderedOptionORM(Base):
    """Association table: the learner-submitted order of options (ORDERING exercises)."""

    __tablename__ = "exercise_answer_ordered_options"
    __table_args__ = (
        UniqueConstraint(
            "answer_id", "sequence_index", name="uq_answer_ordered_options_sequence"
        ),
    )

    answer_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("exercise_answers.answer_id", ondelete="CASCADE"),
        primary_key=True,
    )
    option_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("exercise_options.option_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    sequence_index: Mapped[int] = mapped_column(Integer, nullable=False)

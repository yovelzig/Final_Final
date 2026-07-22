"""ORM model for the `learning_session_activities` table."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class LearningSessionActivityORM(Base):
    """One recommended-and-tracked exercise slot within a `LearningSession`."""

    __tablename__ = "learning_session_activities"
    __table_args__ = (
        UniqueConstraint("session_id", "position", name="uq_session_activities_session_position"),
        Index("ix_session_activities_session_id", "session_id"),
        Index("ix_session_activities_learner_id", "learner_id"),
        Index("ix_session_activities_exercise_id", "exercise_id"),
    )

    activity_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("learning_sessions.session_id", ondelete="CASCADE"),
        nullable=False,
    )
    learner_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("learner_profiles.learner_id", ondelete="RESTRICT"),
        nullable=False,
    )
    exercise_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("exercises.exercise_id", ondelete="RESTRICT"), nullable=False
    )
    attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("exercise_attempts.attempt_id", ondelete="RESTRICT"),
        nullable=True,
    )
    decision_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("adaptive_decisions.decision_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    recommended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    skipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

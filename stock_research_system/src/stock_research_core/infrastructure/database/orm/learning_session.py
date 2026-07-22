"""ORM model for the `learning_sessions` table."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class LearningSessionORM(Base):
    """One learner's bounded practice session."""

    __tablename__ = "learning_sessions"
    __table_args__ = (
        Index("ix_learning_sessions_status", "status"),
        Index("ix_learning_sessions_session_type", "session_type"),
        Index("ix_learning_sessions_learner_status", "learner_id", "status"),
        Index("ix_learning_sessions_started_at", "started_at"),
    )

    session_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    learner_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("learner_profiles.learner_id", ondelete="RESTRICT"),
        nullable=False,
    )
    session_type: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    goal_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    abandoned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recommended_item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    correct_item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_score: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False, default=0)
    maximum_score: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False, default=0)
    policy_version: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

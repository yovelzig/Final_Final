"""ORM model for the `tutor_conversations` table."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class TutorConversationORM(Base):
    """A learner's conversation thread with the grounded AI tutor."""

    __tablename__ = "tutor_conversations"
    __table_args__ = (
        Index("ix_tutor_conversations_learner_status", "learner_id", "status"),
        Index("ix_tutor_conversations_context_type", "context_type"),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    learner_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("learner_profiles.learner_id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    context_type: Mapped[str] = mapped_column(String(50), nullable=False)

    lesson_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("lessons.lesson_id", ondelete="RESTRICT"), nullable=True
    )
    exercise_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("exercises.exercise_id", ondelete="RESTRICT"), nullable=True
    )
    scenario_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("historical_market_scenarios.scenario_id", ondelete="RESTRICT"),
        nullable=True,
    )
    portfolio_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("virtual_portfolios.portfolio_id", ondelete="RESTRICT"), nullable=True
    )

    knowledge_cutoff_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

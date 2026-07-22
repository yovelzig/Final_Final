"""ORM model for the `learning_orchestrator_threads` table (Phase 12)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class LearningOrchestratorThreadORM(Base):
    """A learner-owned coaching thread. Maps to the domain
    `LearningOrchestratorThread`. Never stores LangGraph checkpoint bytes -
    those live in the official checkpointer's own tables."""

    __tablename__ = "learning_orchestrator_threads"
    __table_args__ = (
        Index("ix_learning_orchestrator_threads_learner_updated", "learner_id", "updated_at"),
        Index("ix_learning_orchestrator_threads_status", "status"),
    )

    thread_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    learner_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("learner_profiles.learner_id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    current_context_type: Mapped[str] = mapped_column(String(32), nullable=False)
    linked_tutor_conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tutor_conversations.conversation_id", ondelete="SET NULL"), nullable=True
    )

    graph_name: Mapped[str] = mapped_column(String(100), nullable=False)
    graph_version: Mapped[str] = mapped_column(String(50), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

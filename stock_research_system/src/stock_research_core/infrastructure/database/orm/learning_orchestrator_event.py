"""ORM model for the `learning_orchestrator_events` table (Phase 12)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class LearningOrchestratorEventORM(Base):
    """An immutable, learner-safe audit event. Maps to the domain
    `LearningOrchestratorEvent`."""

    __tablename__ = "learning_orchestrator_events"
    __table_args__ = (
        UniqueConstraint("run_id", "sequence_number", name="uq_learning_orchestrator_events_run_sequence"),
        Index("ix_learning_orchestrator_events_run_sequence", "run_id", "sequence_number"),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("learning_orchestrator_runs.run_id", ondelete="CASCADE"), nullable=False
    )
    thread_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("learning_orchestrator_threads.thread_id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)

    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    learner_message: Mapped[str] = mapped_column(String(1000), nullable=False)
    event_metadata: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, server_default="{}")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

"""ORM model for the `learning_orchestrator_runs` table (Phase 12)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class LearningOrchestratorRunORM(Base):
    """One durable execution of the learning-coach graph. Maps to the
    domain `LearningOrchestratorRun`."""

    __tablename__ = "learning_orchestrator_runs"
    __table_args__ = (
        UniqueConstraint("thread_id", "idempotency_key", name="uq_learning_orchestrator_runs_thread_idempotency"),
        Index("ix_learning_orchestrator_runs_thread_created", "thread_id", "created_at"),
        Index("ix_learning_orchestrator_runs_status", "status"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    thread_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("learning_orchestrator_threads.thread_id", ondelete="CASCADE"), nullable=False
    )
    learner_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("learner_profiles.learner_id", ondelete="RESTRICT"), nullable=False
    )

    input_message_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tutor_messages.message_id", ondelete="SET NULL"), nullable=True
    )
    output_tutor_answer_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tutor_answers.answer_id", ondelete="SET NULL"), nullable=True
    )

    status: Mapped[str] = mapped_column(String(24), nullable=False)
    intent: Mapped[str | None] = mapped_column(String(48), nullable=True)
    route: Mapped[str | None] = mapped_column(String(32), nullable=True)

    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)

    step_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    maximum_steps: Mapped[int] = mapped_column(Integer, nullable=False, server_default="30")

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    waiting_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    failure_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    graph_version: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

"""ORM model for the `learning_orchestrator_action_proposals` table (Phase 12)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class LearningOrchestratorActionProposalORM(Base):
    """A proposed, explicitly-approvable educational action. Maps to the
    domain `LearningActionProposal`."""

    __tablename__ = "learning_orchestrator_action_proposals"
    __table_args__ = (
        UniqueConstraint("run_id", "idempotency_key", name="uq_learning_orchestrator_actions_run_idempotency"),
        Index("ix_learning_orchestrator_actions_status", "status"),
    )

    proposal_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("learning_orchestrator_runs.run_id", ondelete="CASCADE"), nullable=False
    )
    thread_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("learning_orchestrator_threads.thread_id", ondelete="CASCADE"), nullable=False
    )
    learner_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("learner_profiles.learner_id", ondelete="RESTRICT"), nullable=False
    )

    action_type: Mapped[str] = mapped_column(String(48), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(String(1000), nullable=False)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)

    parameters: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    result_reference: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    approval_decision: Mapped[str | None] = mapped_column(String(16), nullable=True)
    approval_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)

    proposed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

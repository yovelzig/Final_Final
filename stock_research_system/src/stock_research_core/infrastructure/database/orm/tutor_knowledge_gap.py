"""ORM models for `tutor_knowledge_gaps` and its skill-association table."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class TutorKnowledgeGapORM(Base):
    """A tracked, normalized instance of an unanswerable learner question."""

    __tablename__ = "tutor_knowledge_gaps"
    __table_args__ = (
        Index("ix_tutor_knowledge_gaps_learner_id", "learner_id"),
        Index("ix_tutor_knowledge_gaps_resolved", "resolved"),
    )

    gap_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    learner_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("learner_profiles.learner_id", ondelete="RESTRICT"), nullable=False
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tutor_conversations.conversation_id", ondelete="RESTRICT"),
        nullable=False,
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tutor_messages.message_id", ondelete="RESTRICT"), nullable=False
    )

    normalized_question: Mapped[str] = mapped_column(String(2000), nullable=False)
    context_type: Mapped[str] = mapped_column(String(50), nullable=False)

    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_document_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("knowledge_documents.document_id", ondelete="RESTRICT"),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class TutorKnowledgeGapSkillORM(Base):
    """Association: which financial skills a knowledge gap relates to."""

    __tablename__ = "tutor_knowledge_gap_skills"

    gap_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tutor_knowledge_gaps.gap_id", ondelete="CASCADE"), primary_key=True
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("financial_skills.skill_id", ondelete="RESTRICT"), primary_key=True
    )

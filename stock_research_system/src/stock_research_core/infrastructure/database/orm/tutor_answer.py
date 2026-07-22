"""ORM model for the `tutor_answers` table."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class TutorAnswerORM(Base):
    """The tutor's response to one learner message, with full lineage."""

    __tablename__ = "tutor_answers"
    __table_args__ = (
        UniqueConstraint("request_message_id", name="uq_tutor_answers_request_message_id"),
        Index("ix_tutor_answers_conversation_created", "conversation_id", "created_at"),
        Index("ix_tutor_answers_status", "status"),
    )

    answer_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tutor_conversations.conversation_id", ondelete="CASCADE"),
        nullable=False,
    )
    request_message_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tutor_messages.message_id", ondelete="RESTRICT"), nullable=False
    )

    status: Mapped[str] = mapped_column(String(20), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(30), nullable=False)

    answer_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    request_category: Mapped[str] = mapped_column(String(50), nullable=False)
    grounding_status: Mapped[str] = mapped_column(String(30), nullable=False)

    retrieval_run_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tutor_retrieval_runs.retrieval_run_id", ondelete="RESTRICT"),
        nullable=True,
    )
    guardrail_decision_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tutor_guardrail_decisions.decision_id", ondelete="RESTRICT"),
        nullable=False,
    )

    tutor_policy_version: Mapped[str] = mapped_column(String(50), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(50), nullable=False)
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    model_response_id: Mapped[str | None] = mapped_column(String(200), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

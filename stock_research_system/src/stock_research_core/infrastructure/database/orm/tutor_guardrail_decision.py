"""ORM model for the `tutor_guardrail_decisions` table."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ARRAY, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class TutorGuardrailDecisionORM(Base):
    """The deterministic guardrail evaluation for one learner message."""

    __tablename__ = "tutor_guardrail_decisions"
    __table_args__ = (
        Index("ix_tutor_guardrail_decisions_conversation_id", "conversation_id"),
        Index("ix_tutor_guardrail_decisions_action", "action"),
    )

    decision_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tutor_conversations.conversation_id", ondelete="CASCADE"),
        nullable=False,
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tutor_messages.message_id", ondelete="RESTRICT"), nullable=False
    )

    request_category: Mapped[str] = mapped_column(String(50), nullable=False)
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    matched_rule_codes: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)

    safe_response_override: Mapped[str | None] = mapped_column(Text, nullable=True)
    policy_version: Mapped[str] = mapped_column(String(50), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

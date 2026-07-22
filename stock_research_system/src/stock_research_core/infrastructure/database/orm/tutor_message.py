"""ORM model for the `tutor_messages` table. Rows are never updated after insert."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class TutorMessageORM(Base):
    """One immutable message within a `TutorConversation`."""

    __tablename__ = "tutor_messages"
    __table_args__ = (Index("ix_tutor_messages_conversation_created", "conversation_id", "created_at"),)

    message_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tutor_conversations.conversation_id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # `clock_timestamp()`, not `now()`: `now()` is transaction start time, so
    # two messages added within the same Unit of Work/transaction (e.g. two
    # `add_message()` calls before a single `commit()`) would otherwise get
    # an identical `created_at` and lose their relative order.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )

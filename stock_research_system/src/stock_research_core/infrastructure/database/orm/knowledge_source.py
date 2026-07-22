"""ORM model for the `knowledge_sources` table."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from stock_research_core.infrastructure.database.base import Base


class KnowledgeSourceORM(Base):
    """An approved (or pending-approval) origin of retrievable FinQuest content."""

    __tablename__ = "knowledge_sources"
    __table_args__ = (
        Index("ix_knowledge_sources_source_type", "source_type"),
        Index("ix_knowledge_sources_approval_status", "approval_status"),
        Index("ix_knowledge_sources_trusted", "trusted"),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    approval_status: Mapped[str] = mapped_column(String(20), nullable=False)
    canonical_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    publisher: Mapped[str | None] = mapped_column(String(300), nullable=True)
    license_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    default_language: Mapped[str] = mapped_column(String(10), nullable=False)
    trusted: Mapped[bool] = mapped_column(Boolean, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
